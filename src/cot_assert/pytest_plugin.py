"""pytest plugin: cot_assert in place of pytest's assertion rewriter.

Off unless enabled with ``--cot-assert`` or ``cot_assert = true`` in the ini
file. pytest's import hook is replaced by cot_assert's, which selects the
modules pytest would (test files, conftests, ``register_assert_rewrite``)
and caches them as the standalone hook does, under a name of its own.
Works with pytest 4.6 (Python 2.7) and current pytest.
"""

from __future__ import absolute_import, division, print_function

import os
import sys
import types

if sys.version_info[0] > 2:
    import importlib.util

import pytest
from _pytest.assertion.rewrite import AssertionRewritingHook
from _pytest.pathlib import fnmatch_ex

from . import _hook, _render
from ._error import AnnotatedAssertion
from ._rewrite import DONT_REWRITE

FINALIZE_MODES = ("message", "notes")


def pytest_addoption(parser):
    group = parser.getgroup("cot_assert")
    group.addoption(
        "--cot-assert",
        action="store_true",
        default=None,
        help="rewrite asserts with cot_assert instead of pytest's rewriter",
    )
    parser.addini(
        "cot_assert",
        type="bool",
        default=False,
        help="rewrite asserts with cot_assert instead of pytest's rewriter",
    )
    parser.addini(
        "cot_assert_finalize",
        default="message",
        help="where a failed assert's explanation goes: message or notes",
    )


def _enabled(config):
    # during pytest_load_initial_conftests only the early parse has run
    option = getattr(config.known_args_namespace, "cot_assert", None)
    if option is not None:
        return option
    return config.getini("cot_assert")


@pytest.hookimpl(tryfirst=True)
def pytest_load_initial_conftests(early_config, parser, args):
    # before pytest imports (and rewrites) the first conftest
    if not _enabled(early_config):
        return
    mode = early_config.getini("cot_assert_finalize")
    if mode not in FINALIZE_MODES:
        raise pytest.UsageError(
            "cot_assert_finalize must be one of %s, not %r"
            % (", ".join(FINALIZE_MODES), mode)
        )
    active = _Active(mode)
    active.apply(early_config)
    early_config.pluginmanager.register(active, "cot_assert_active")
    early_config.add_cleanup(active.undo)


class _Active(object):
    def __init__(self, finalize_mode):
        self.finalize_mode = finalize_mode
        self.swapped = None

    def apply(self, config):
        state = _assertion_state(config)
        # --assert=plain installs no hook, and neither do we
        if state is not None and state.hook is not None:
            self.swapped = _HookSwap(config, state)
        self.previous_formatter = _render.set_formatter(PytestFormatter())

    def undo(self):
        if self.swapped is not None:
            self.swapped.undo()
        _render.set_formatter(self.previous_formatter)

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        # render while pytest's comparison hook and config are still set,
        # before the report turns the exception into text
        excinfo = call.excinfo
        if excinfo is not None and isinstance(excinfo.value, AnnotatedAssertion):
            excinfo.value.finalize(self.finalize_mode)
        yield

    def pytest_report_header(self, config):
        return "cot_assert: rewriting asserts (finalize into %s)" % (
            self.finalize_mode,
        )


def _assertion_state(config):
    try:
        from _pytest.assertion.rewrite import assertstate_key
    except ImportError:
        # pytest 4.6
        return getattr(config, "_assertstate", None)
    return config.stash.get(assertstate_key, None)


class _HookSwap(object):
    """pytest's import hook out, ours in, wherever pytest holds it."""

    def __init__(self, config, state):
        self.config = config
        self.state = state
        self.pytest_hook = state.hook
        # plugins from entry points are marked before our first hook runs
        self.hook = PytestRewriteHook(config, self.pytest_hook._must_rewrite)
        self._put(self.pytest_hook, self.hook)

    def undo(self):
        self._put(self.hook, self.pytest_hook)

    def _put(self, old, new):
        sys.meta_path[sys.meta_path.index(old)] = new
        self.state.hook = new
        self.config.pluginmanager.rewrite_hook = new


NEVER_REWRITTEN = _hook.STDLIB | frozenset(["pytest", "_pytest"])


class PytestRewriteHook(_hook.RewriteHook, AssertionRewritingHook):
    """cot_assert's import hook, selecting modules by pytest's rules.

    Test files by ``python_files``, conftests, files named on the command
    line, and modules marked by ``register_assert_rewrite`` or as plugins.
    It derives from pytest's hook only because ``register_assert_rewrite``
    looks for an instance of it on ``sys.meta_path``; none of pytest's
    methods run (see the end of this class).
    """

    def __init__(self, config, marked=()):
        self.config = config
        try:
            self.fnpats = config.getini("python_files")
        except ValueError:
            self.fnpats = ["test_*.py", "*_test.py"]
        self.session = None
        self._marked = set(marked)
        self._marked_cache = {}
        self._basenames = set(["conftest"])
        self._session_basenames_added = False
        self._origins = {}
        if _hook.PY2:
            _hook.RewriteHook.__init__(self, ())

    if not _hook.PY2:
        # The loader of what it rewrites is the hook itself, as with pytest's:
        # pytest-dev/pytest#15022 tells a rewritten module by its loader.
        # The work is the standalone hook's loader's.

        def find_spec(self, fullname, path=None, target=None):
            spec = _hook.RewriteHook.find_spec(self, fullname, path, target)
            if spec is None:
                return None
            self._origins[fullname] = spec.origin
            return importlib.util.spec_from_file_location(
                fullname,
                spec.origin,
                loader=self,
                submodule_search_locations=spec.submodule_search_locations,
            )

        def create_module(self, spec):
            return None

        def exec_module(self, module):
            self._loader(module.__name__).exec_module(module)

        def get_resource_reader(self, name):
            return self._loader(name).get_resource_reader(name)

        def get_data(self, pathname):
            with open(pathname, "rb") as f:
                return f.read()

        def _loader(self, name):
            return _hook.RewritingLoader(name, self._origins[name])

    def set_session(self, session):
        self.session = session
        self._session_basenames_added = False

    def wants(self, fullname):
        # by name alone, before the costly lookup; true when unsure
        root = fullname.partition(".")[0]
        if root == "cot_assert":
            # marked as a plugin by pytest, but rewriting it would need itself
            return False
        if root in NEVER_REWRITTEN:
            # string operations only, see _hook.STDLIB
            return self._is_marked(fullname)
        if self.session is not None and not self._session_basenames_added:
            self._session_basenames_added = True
            for path in self.session._initialpaths:
                head, name = os.path.split(str(path))
                if name == "__init__.py":
                    # imported under the name of its package
                    name = os.path.basename(head)
                self._basenames.add(os.path.splitext(name)[0])
        parts = fullname.split(".")
        if parts[-1] in self._basenames:
            return True
        as_path = os.sep.join(parts) + ".py"
        for pattern in self.fnpats:
            # "tests/**.py" needs the real path
            if os.path.dirname(pattern) or fnmatch_ex(pattern, as_path):
                return True
        return self._is_marked(fullname)

    def _should_rewrite(self, name, fn, state=None):
        # pytest-dev/pytest#15022 asks the hook this about an imported module
        return self.accepts(name, os.fspath(fn) if hasattr(os, "fspath") else fn)

    def accepts(self, fullname, filename):
        if os.path.basename(filename) == "conftest.py":
            return True
        if self.session is not None and self.session.isinitpath(
            os.path.abspath(filename)
        ):
            return True
        for pattern in self.fnpats:
            if fnmatch_ex(pattern, filename):
                return True
        return self._is_marked(fullname)

    def _is_marked(self, fullname):
        try:
            return self._marked_cache[fullname]
        except KeyError:
            marked = any(
                fullname == name or fullname.startswith(name + ".")
                for name in self._marked
            )
            self._marked_cache[fullname] = marked
            return marked

    def mark_rewrite(self, *names):
        """Rewrite these modules and packages, and their submodules, on import."""
        for name in set(names).intersection(sys.modules):
            module = sys.modules[name]
            loader = getattr(module, "__loader__", None)
            if isinstance(loader, _hook.LOADERS + (PytestRewriteHook,)):
                continue
            doc = module.__doc__ or ""
            if any(marker in doc for marker in DONT_REWRITE):
                continue
            self._warn_already_imported(name)
        self._marked.update(names)
        self._marked_cache.clear()

    def _warn_already_imported(self, name):
        from _pytest.warning_types import PytestAssertRewriteWarning

        warning = PytestAssertRewriteWarning(
            "Module already imported so cannot be rewritten: %s" % (name,)
        )
        if hasattr(self.config, "issue_config_time_warning"):
            self.config.issue_config_time_warning(warning, stacklevel=5)
        else:
            # pytest 4.6
            from _pytest.warnings import _issue_warning_captured

            _issue_warning_captured(warning, self.config.hook, stacklevel=5)


def _not_used(name):
    def refuse(self, *args, **kwargs):
        raise NotImplementedError(
            "pytest's AssertionRewritingHook.%s is not used by cot_assert" % (name,)
        )

    refuse.__name__ = name
    return refuse


# whatever pytest's hook does beyond what this one does, it does not do here;
# a pytest release that adds to its hook fails loudly instead of half-working
for _name, _value in list(vars(AssertionRewritingHook).items()):
    if isinstance(_value, types.FunctionType) and not hasattr(_hook.RewriteHook, _name):
        if _name not in vars(PytestRewriteHook):
            setattr(PytestRewriteHook, _name, _not_used(_name))
del _name, _value


class PytestFormatter(_render.Formatter):
    """Formatting through pytest's own helpers, as its rewriter does."""

    def saferepr(self, obj):
        from _pytest.assertion.rewrite import _saferepr

        return _saferepr(obj)

    def format_assertmsg(self, obj):
        from _pytest.assertion.rewrite import _format_assertmsg

        # pytest doubles % for the %-formatting its template goes through;
        # nothing formats this text again
        return _format_assertmsg(obj).replace("%%", "%")

    def format_explanation(self, explanation):
        from _pytest.assertion.util import format_explanation

        return format_explanation(explanation)

    def reprcompare(self, op, left, right):
        from _pytest.assertion import util

        if util._reprcompare is None:
            return None
        return util._reprcompare(op, left, right)

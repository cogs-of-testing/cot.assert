"""pytest plugin: cot_assert in place of pytest's assertion rewriter.

Off unless enabled with ``--cot-assert`` or ``cot_assert = true`` in the ini
file. pytest keeps choosing which files to rewrite (test files, conftests,
``register_assert_rewrite``) and keeps caching them; only the rewriting
itself is swapped, and the cache name changes so neither rewriter picks up
the other's bytecode. Works with pytest 4.6 (Python 2.7) and current pytest.
"""

from __future__ import absolute_import, division, print_function

import pytest

from . import _cache, _hook, _render
from ._error import AnnotatedAssertion
from ._rewrite import rewrite_asserts

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
    patch = _PytestPatch(mode)
    patch.apply()
    early_config.pluginmanager.register(patch, "cot_assert_active")
    early_config.add_cleanup(patch.undo)


class _PytestPatch(object):
    def __init__(self, finalize_mode):
        self.finalize_mode = finalize_mode
        self.saved = []

    def apply(self):
        from _pytest.assertion import rewrite as pytest_rewrite

        self._set(pytest_rewrite, "rewrite_asserts", _pytest_rewrite_asserts)
        self._set(
            pytest_rewrite,
            "PYC_TAIL",
            pytest_rewrite.PYC_TAIL.replace(
                pytest_rewrite.PYC_EXT, "-" + _hook.CACHE_TAG + pytest_rewrite.PYC_EXT
            ),
        )
        # pytest checks its cache by source mtime and size; ours is checked by
        # source hash and follows a moved source, see _cache
        self._set(pytest_rewrite, "_read_pyc", _pytest_read_pyc)
        self._set(
            pytest_rewrite,
            "_rewrite_test",
            _hashing_rewrite_test(pytest_rewrite._rewrite_test),
        )
        self._set(pytest_rewrite, "_write_pyc", _pytest_write_pyc)
        self.previous_formatter = _render.set_formatter(PytestFormatter())

    def _set(self, obj, name, value):
        self.saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self):
        while self.saved:
            obj, name, value = self.saved.pop()
            setattr(obj, name, value)
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


def _pytest_rewrite_asserts(mod, *args, **kwargs):
    # pytest 4.6: (mod, module_path, config); current: (mod, source, path, config)
    rewrite_asserts(mod)


def _pytest_read_pyc(source, pyc, trace=lambda text: None):
    return _cache.read(str(pyc), str(source), trace)


def _hashing_rewrite_test(rewrite_test):
    # pytest 4.6: (config, fn); current: (fn, config). Either way pytest reads
    # the source itself, so the hash is taken before it does.
    def _rewrite_test(*args):
        fn = args[1] if hasattr(args[0], "getini") else args[0]
        try:
            hash_ = _cache.read_source_hash(str(fn))
        except (IOError, OSError):
            hash_ = None
        _, co = rewrite_test(*args)
        if co is None or hash_ is None:
            return None, co
        return hash_, co

    return _rewrite_test


def _pytest_write_pyc(state, co, hash_, pyc):
    if hash_ is None:
        return False
    return _cache.write(str(pyc), hash_, co, state.trace)


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

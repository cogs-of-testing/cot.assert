"""Importing the pytest11 plugin must not need pytest's private modules.

cot-assert is a ``pytest11`` entry point, so its plugin module is imported on
every pytest run in an environment it is installed in, even when cot-assert
itself is off.  The private ``_pytest`` modules the plugin needs internally
belong to the activation path (``--cot-assert``): a pytest release that moves
them may then break opted-in runs, but never every run (issue #13).
"""

import importlib
import sys


class _BlockPytestPrivates(object):
    """A meta-path finder that refuses the private modules at import time.

    Raising inside ``find_module``/``find_spec`` aborts the import instead of
    letting a later finder succeed, so the plugin cannot quietly import them.
    """

    _blocked = ("_pytest.assertion.rewrite", "_pytest.pathlib")

    def find_module(self, fullname, path=None):
        if fullname in self._blocked:
            raise ImportError("blocked for this test: %s" % fullname)
        return None

    if sys.version_info[0] >= 3:

        def find_spec(self, fullname, path=None, target=None):
            if fullname in self._blocked:
                raise ImportError("blocked for this test: %s" % fullname)
            return None


def test_plugin_imports_without_private_pytest_modules():
    blocked = _BlockPytestPrivates._blocked
    saved = dict((name, sys.modules.pop(name)) for name in blocked if name in sys.modules)
    saved_plugin = sys.modules.pop("cot_assert.pytest_plugin", None)
    sys.meta_path.insert(0, _BlockPytestPrivates())
    try:
        # red before the fix: the module-level private imports raise here
        importlib.import_module("cot_assert.pytest_plugin")
    finally:
        del sys.meta_path[0]
        sys.modules.update(saved)
        if saved_plugin is not None:
            sys.modules["cot_assert.pytest_plugin"] = saved_plugin


def test_activation_still_builds_the_hook_from_private_modules():
    # the private imports moved, they did not disappear: building the rewrite
    # hook (what --cot-assert does) still derives from pytest's hook
    plugin = importlib.import_module("cot_assert.pytest_plugin")
    assert plugin._PYTEST_REWRITE_HOOK_CACHE is None  # not activated by this import
    hook = plugin._pytest_rewrite_hook()
    try:
        assert hook.__name__ == "PytestRewriteHook"
        assert plugin._pytest_rewrite_hook() is hook  # built once, then cached
    finally:
        plugin._PYTEST_REWRITE_HOOK_CACHE = None

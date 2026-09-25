from __future__ import absolute_import, division, print_function

import os
import sys
import textwrap
import traceback

import pytest

import cot_assert
from cot_assert import AnnotatedAssertion

PY2 = sys.version_info[0] == 2

FAILING = """
def check(x):
    assert x == 2
"""


@pytest.fixture
def tree(tmpdir, monkeypatch):
    """A fresh sys.path entry; modules imported from it are forgotten after."""
    monkeypatch.syspath_prepend(str(tmpdir))

    def write(relpath, source=FAILING):
        path = tmpdir.join(relpath)
        path.dirpath().ensure(dir=True)
        path.write(textwrap.dedent(source))
        return path

    yield write
    root = str(tmpdir)
    for name, module in list(sys.modules.items()):
        if (getattr(module, "__file__", None) or "").startswith(root):
            del sys.modules[name]


@pytest.fixture
def hook():
    hooks = []

    def install(*patterns):
        hooks.append(cot_assert.install(patterns))
        return hooks[-1]

    yield install
    for installed in hooks:
        cot_assert.uninstall(installed)


def import_module(name):
    __import__(name)
    return sys.modules[name]


def raised(module, *args):
    with pytest.raises(AssertionError) as excinfo:
        module.check(*args)
    return excinfo.value


def test_matching_module_is_rewritten(tree, hook):
    tree("rewritten_mod.py")
    tree("plain_mod.py")
    hook("rewritten_mod")
    exc = raised(import_module("rewritten_mod"), 1)
    assert isinstance(exc, AnnotatedAssertion)
    assert str(exc) == "assert 1 == 2"
    assert not isinstance(raised(import_module("plain_mod"), 1), AnnotatedAssertion)


def test_package_name_selects_submodules(tree, hook):
    tree("pkg_sel/__init__.py", FAILING)
    tree("pkg_sel/sub.py")
    hook("pkg_sel")
    assert isinstance(raised(import_module("pkg_sel"), 1), AnnotatedAssertion)
    assert isinstance(raised(import_module("pkg_sel.sub"), 1), AnnotatedAssertion)


def test_glob_matches_last_component(tree, hook):
    tree("pkg_glob/__init__.py", "")
    tree("pkg_glob/test_it.py")
    tree("pkg_glob/helper.py")
    hook("test_*")
    assert isinstance(raised(import_module("pkg_glob.test_it"), 1), AnnotatedAssertion)
    helper = raised(import_module("pkg_glob.helper"), 1)
    assert not isinstance(helper, AnnotatedAssertion)


def test_plain_name_does_not_match_last_component(tree, hook):
    tree("pkg_plain/__init__.py", "")
    tree("pkg_plain/target.py")
    hook("target")
    exc = raised(import_module("pkg_plain.target"), 1)
    assert not isinstance(exc, AnnotatedAssertion)


def test_uninstall_stops_rewriting(tree, hook):
    tree("after_uninstall.py")
    cot_assert.uninstall(hook("after_uninstall"))
    exc = raised(import_module("after_uninstall"), 1)
    assert not isinstance(exc, AnnotatedAssertion)


def test_traceback_shows_source(tree, hook):
    tree("with_source.py")
    hook("with_source")
    module = import_module("with_source")
    try:
        module.check(1)
    except AssertionError:
        text = traceback.format_exc()
    assert "assert x == 2" in text
    assert "with_source.py" in text


def test_cache_not_written_without_bytecode(tree, hook, monkeypatch):
    from cot_assert._hook import cache_path

    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    path = tree("nocache_mod.py")
    hook("nocache_mod")
    import_module("nocache_mod")
    assert not os.path.exists(cache_path(str(path)))


@pytest.mark.skipif(sys.dont_write_bytecode, reason="writes no bytecode here")
class TestCache(object):
    def cached(self, path):
        from cot_assert._hook import cache_path

        return cache_path(str(path))

    def test_written_next_to_regular_cache(self, tree, hook):
        path = tree("cached_mod.py")
        hook("cached_mod")
        import_module("cached_mod")
        cache = self.cached(path)
        assert os.path.exists(cache)
        assert cot_assert._hook.CACHE_TAG in os.path.basename(cache)

    def test_used_on_next_import(self, tree, hook, monkeypatch):
        path = tree("reused_mod.py")
        hook("reused_mod")
        import_module("reused_mod")
        del sys.modules["reused_mod"]

        def no_rewrite(*args):
            raise AssertionError("rewrote again")

        monkeypatch.setattr(cot_assert._hook, "rewrite_source", no_rewrite)
        exc = raised(import_module("reused_mod"), 1)
        assert str(exc) == "assert 1 == 2"
        assert os.path.exists(self.cached(path))

    def test_stale_after_source_changes(self, tree, hook):
        path = tree("changed_mod.py")
        hook("changed_mod")
        import_module("changed_mod")
        del sys.modules["changed_mod"]
        st = os.stat(str(path))
        path.write(textwrap.dedent(FAILING).replace("== 2", "== 3"))
        # same size and mtime: only the source hash tells them apart
        os.utime(str(path), (st.st_atime, st.st_mtime))
        exc = raised(import_module("changed_mod"), 1)
        assert str(exc) == "assert 1 == 3"

    def test_follows_a_moved_source(self, tree, hook, monkeypatch, tmpdir):
        old = tree("before/moved_mod.py")
        monkeypatch.syspath_prepend(str(old.dirpath()))
        hook("moved_mod")
        import_module("moved_mod")
        del sys.modules["moved_mod"]
        sys.path.remove(str(old.dirpath()))
        old.dirpath().rename(tmpdir.join("after"))
        new = tmpdir.join("after", "moved_mod.py")
        monkeypatch.syspath_prepend(str(new.dirpath()))

        def no_rewrite(*args):
            raise AssertionError("rewrote again")

        monkeypatch.setattr(cot_assert._hook, "rewrite_source", no_rewrite)
        module = import_module("moved_mod")
        assert module.check.__code__.co_filename == str(new)

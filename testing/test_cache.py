from __future__ import absolute_import, division, print_function

import os

import pytest

from cot_assert import _cache

SOURCE = b"def outer():\n    def inner():\n        pass\n    return inner\n"


def compiled(path):
    return compile(SOURCE, str(path), "exec")


def nested_filenames(code):
    names = [code.co_filename]
    for const in code.co_consts:
        if isinstance(const, type(code)):
            names.extend(nested_filenames(const))
    return names


@pytest.fixture
def source(tmpdir):
    path = tmpdir.join("mod.py")
    path.write_binary(SOURCE)
    return path


@pytest.fixture
def pyc(tmpdir):
    return str(tmpdir.join("__pycache__", "mod.tag-cot_assert-new.pyc"))


def test_round_trip(source, pyc):
    assert _cache.write(pyc, _cache.source_hash(SOURCE), compiled(source))
    code = _cache.read(pyc, str(source))
    assert nested_filenames(code) == [str(source)] * 3


def test_stale_after_same_size_edit_with_same_mtime(source, pyc):
    _cache.write(pyc, _cache.source_hash(SOURCE), compiled(source))
    st = os.stat(str(source))
    source.write_binary(SOURCE.replace(b"inner", b"INNER"))
    os.utime(str(source), (st.st_atime, st.st_mtime))
    assert _cache.read(pyc, str(source)) is None


def test_mtime_alone_does_not_invalidate(source, pyc):
    _cache.write(pyc, _cache.source_hash(SOURCE), compiled(source))
    os.utime(str(source), (1, 1))
    assert _cache.read(pyc, str(source)) is not None


def test_timestamp_pyc_is_stale(source, pyc):
    # the layout before 0.2.3: flags 0, then mtime and size
    os.makedirs(os.path.dirname(pyc))
    with open(pyc, "wb") as f:
        f.write(_cache.MAGIC + b"\x00" * 12)
    assert _cache.read(pyc, str(source)) is None


@pytest.mark.parametrize("native", [True, False], ids=["imp", "fallback"])
def test_moved_source_keeps_cache_and_takes_new_path(
    tmpdir, source, pyc, native, monkeypatch
):
    if not native:
        monkeypatch.setattr(_cache, "_fix_co_filename", None)
    _cache.write(pyc, _cache.source_hash(SOURCE), compiled("/elsewhere/mod.py"))
    code = _cache.read(pyc, str(source))
    assert nested_filenames(code) == [str(source)] * 3


def test_write_prunes_other_digests_only(tmpdir, source, pyc):
    cache_dir = tmpdir.join("__pycache__").ensure(dir=True)
    kept = [
        "mod.tag.pyc",  # the interpreter's own
        "mod.othertag-cot_assert-old.pyc",  # another interpreter
        "mod.tag-cot_assert-old.pyo",
        "mod.tag-cot_assert-old.pyc.123",  # another process, mid-write
        "other.tag-cot_assert-old.pyc",
    ]
    for name in kept + ["mod.tag-cot_assert-old.pyc"]:
        cache_dir.join(name).write("")
    _cache.write(pyc, _cache.source_hash(SOURCE), compiled(source))
    assert sorted(os.listdir(str(cache_dir))) == sorted(
        kept + ["mod.tag-cot_assert-new.pyc"]
    )


def test_unwritable_directory_goes_without(source, tmpdir):
    blocker = tmpdir.join("__pycache__")
    blocker.write("a file, not a directory")
    pyc = str(blocker.join("mod.tag-cot_assert-new.pyc"))
    assert not _cache.write(pyc, _cache.source_hash(SOURCE), compiled(source))
    assert _cache.read(pyc, str(source)) is None

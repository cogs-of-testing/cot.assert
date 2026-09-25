"""Bytecode cache files for rewritten modules.

A cache file is a checked-hash pyc (PEP 552): the magic number, flags 3, then
8 bytes of the source's hash. mtime and size miss same-size edits within one
second and reject every file of a fresh checkout or a restored cache, whose
sources all carry new mtimes. Only cot_assert reads these files, so Python 2
uses the same layout with a hash of its own.
"""

from __future__ import absolute_import, division, print_function

import hashlib
import marshal
import os
import sys
import types

PY2 = sys.version_info[0] == 2

if PY2:
    import imp

    MAGIC = imp.get_magic()
    _fix_co_filename = None

    def source_hash(data):
        return hashlib.sha1(data).digest()[:8]

else:
    import importlib.util

    MAGIC = importlib.util.MAGIC_NUMBER
    try:
        from _imp import _fix_co_filename
    except ImportError:  # pragma: no cover
        _fix_co_filename = None

    def source_hash(data):
        return importlib.util.source_hash(data)[:8]


FLAGS = b"\x03\x00\x00\x00"
HEADER_SIZE = len(MAGIC) + len(FLAGS) + 8
DIGEST_MARK = "cot_assert-"


def read_source_hash(source_path):
    with open(source_path, "rb") as f:
        return source_hash(f.read())


def read(pyc, source_path, trace=None):
    """The cached code for ``source_path``, or None when missing or stale."""
    trace = trace or (lambda text: None)
    try:
        with open(pyc, "rb") as f:
            header = f.read(HEADER_SIZE)
            data = f.read()
    except (IOError, OSError):
        return None
    try:
        current = read_source_hash(source_path)
    except (IOError, OSError) as e:
        trace("cot_assert cache %s: %s" % (pyc, e))
        return None
    if header != MAGIC + FLAGS + current:
        trace("cot_assert cache %s: out of date" % (pyc,))
        return None
    try:
        code = marshal.loads(data)
    except (EOFError, ValueError, TypeError):
        trace("cot_assert cache %s: unreadable" % (pyc,))
        return None
    if not isinstance(code, types.CodeType):
        return None
    # the source may have moved with its __pycache__ (a renamed package, the
    # same tree mounted elsewhere); importlib keeps such a pyc and points it
    # at the new path, and so do we
    return fix_filename(code, str(source_path))


def write(pyc, hash_, code, trace=None):
    """Store ``code`` under ``hash_``, of the source bytes it was built from.

    Where those bytes are not at hand, a hash taken before they were read
    will do: a source edited in between leaves a cache that no longer
    matches, rather than one that matches the wrong code.
    """
    trace = trace or (lambda text: None)
    data = MAGIC + FLAGS + hash_ + marshal.dumps(code)
    directory = os.path.dirname(pyc)
    tmp = "%s.%d" % (pyc, os.getpid())
    try:
        if not os.path.isdir(directory):
            os.makedirs(directory)
        with open(tmp, "wb") as f:
            f.write(data)
        _replace(tmp, pyc)
    except (IOError, OSError) as e:
        # read-only trees just go without a cache
        trace("cot_assert cache %s: not written: %s" % (pyc, e))
        try:
            os.unlink(tmp)
        except (IOError, OSError):
            pass
        return False
    prune(pyc)
    return True


def prune(pyc):
    """Remove the files an earlier cot_assert left for the same source.

    Only those that differ in the rewriter digest alone: the rest of the
    name is the interpreter (and under pytest, pytest's version), and a
    tree shared by several of those keeps a valid file for each.
    """
    directory, name = os.path.split(pyc)
    prefix, mark, _ = name.rpartition(DIGEST_MARK)
    if not mark:
        return
    prefix += mark
    ext = os.path.splitext(name)[1]
    try:
        names = os.listdir(directory)
    except (IOError, OSError):
        return
    for other in names:
        # "name.pyc.<pid>" is another process still writing
        if other == name or not other.startswith(prefix) or not other.endswith(ext):
            continue
        try:
            os.unlink(os.path.join(directory, other))
        except (IOError, OSError):
            pass


def fix_filename(code, filename):
    """Point ``code`` and the code objects nested in it at ``filename``."""
    if code.co_filename == filename:
        return code
    if _fix_co_filename is not None:
        _fix_co_filename(code, filename)  # in place, recursive
        return code
    return _replace_filename(code, filename)


def _replace_filename(code, filename):
    consts = tuple(
        _replace_filename(c, filename) if isinstance(c, types.CodeType) else c
        for c in code.co_consts
    )
    if not PY2:
        return code.replace(co_filename=filename, co_consts=consts)
    return types.CodeType(
        code.co_argcount,
        code.co_nlocals,
        code.co_stacksize,
        code.co_flags,
        code.co_code,
        consts,
        code.co_names,
        code.co_varnames,
        filename,
        code.co_name,
        code.co_firstlineno,
        code.co_lnotab,
        code.co_freevars,
        code.co_cellvars,
    )


if PY2:

    def _replace(src, dst):
        # atomic on POSIX; Windows cannot rename over an existing file
        if os.name == "nt" and os.path.exists(dst):
            os.unlink(dst)
        os.rename(src, dst)

else:
    _replace = os.replace

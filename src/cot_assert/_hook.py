"""Import hook that rewrites the asserts of selected modules."""

from __future__ import absolute_import, division, print_function

import fnmatch
import hashlib
import os
import sys

from ._rewrite import rewrite_source

PY2 = sys.version_info[0] == 2


def _rewriter_digest():
    """Changes whenever the code that shapes rewritten modules changes.

    Cached bytecode is only valid for the rewriter that produced it; hashing
    the sources avoids having to remember a version bump.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    digest = hashlib.sha1()
    for name in ("_rewrite.py", "_unparse.py"):
        try:
            with open(os.path.join(here, name), "rb") as f:
                digest.update(f.read())
        except (IOError, OSError):
            return "unknown"
    return digest.hexdigest()[:10]


CACHE_TAG = "cot_assert-" + _rewriter_digest()


class _Matcher(object):
    def __init__(self, patterns):
        self.patterns = list(patterns)

    def __call__(self, fullname):
        if fullname == "cot_assert" or fullname.startswith("cot_assert."):
            return False
        for pattern in self.patterns:
            if fnmatch.fnmatchcase(fullname, pattern):
                return True
            # a package name selects its submodules too
            if fullname.startswith(pattern + "."):
                return True
            # a wildcard pattern like "test_*" matches the last dotted component
            last = fullname.rpartition(".")[2]
            if _is_glob(pattern) and "." not in pattern:
                if fnmatch.fnmatchcase(last, pattern):
                    return True
        return False


def _is_glob(pattern):
    return any(char in pattern for char in "*?[")


def install(match):
    """Rewrite asserts in modules imported from now on whose name matches.

    ``match`` is a list of module names (selecting their submodules too) or
    fnmatch patterns; a wildcard pattern without dots also matches the last
    component of a dotted name. Returns the hook; ``uninstall(hook)`` removes it.
    """
    hook = RewriteHook(match)
    sys.meta_path.insert(0, hook)
    return hook


def uninstall(hook):
    try:
        sys.meta_path.remove(hook)
    except ValueError:
        pass


if not PY2:
    import importlib.machinery
    import importlib.util
    import marshal

    class RewriteHook(object):
        def __init__(self, match):
            self.matches = _Matcher(match)

        def find_spec(self, fullname, path=None, target=None):
            if not self.matches(fullname):
                return None
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
            if spec is None or not isinstance(
                spec.loader, importlib.machinery.SourceFileLoader
            ):
                return None
            spec.loader = RewritingLoader(fullname, spec.origin)
            return spec

        def invalidate_caches(self):
            pass

    class RewritingLoader(importlib.machinery.SourceFileLoader):
        """A source loader whose code has its asserts rewritten.

        It keeps its own bytecode cache next to the regular one; the regular
        ``__pycache__`` entry holds unrewritten code and must not be used.
        """

        def get_code(self, fullname):
            path = self.get_filename(fullname)
            st = os.stat(path)
            cache = cache_path(path)
            code = _read_cache(cache, st)
            if code is None:
                code = rewrite_source(self.get_data(path), path)
                if not sys.dont_write_bytecode:
                    _write_cache(cache, st, code)
            return code

    def cache_path(source_path):
        directory, filename = os.path.split(source_path)
        stem = filename.rpartition(".")[0]
        tag = sys.implementation.cache_tag
        return os.path.join(
            directory, "__pycache__", "%s.%s-%s.pyc" % (stem, tag, CACHE_TAG)
        )

    def _header(st):
        return (
            importlib.util.MAGIC_NUMBER
            + (0).to_bytes(4, "little")
            + (int(st.st_mtime) & 0xFFFFFFFF).to_bytes(4, "little")
            + (st.st_size & 0xFFFFFFFF).to_bytes(4, "little")
        )

    def _read_cache(cache, st):
        try:
            with open(cache, "rb") as f:
                data = f.read()
        except OSError:
            return None
        header = _header(st)
        if data[: len(header)] != header:
            return None
        try:
            return marshal.loads(data[len(header) :])
        except (EOFError, ValueError, TypeError):
            return None

    def _write_cache(cache, st, code):
        data = _header(st) + marshal.dumps(code)
        tmp = "%s.%d" % (cache, os.getpid())
        try:
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, cache)
        except OSError:
            # read-only trees just go without a cache
            try:
                os.unlink(tmp)
            except OSError:
                pass

else:
    import imp

    class RewriteHook(object):
        """PEP 302 finder and loader; Python 2 goes without a disk cache."""

        def __init__(self, match):
            self.matches = _Matcher(match)
            self._found = {}
            self._sources = {}

        def find_module(self, fullname, path=None):
            if not self.matches(fullname):
                return None
            name = fullname.rpartition(".")[2]
            try:
                fd, pathname, (_, _, kind) = imp.find_module(name, path)
            except ImportError:
                return None
            if fd is not None:
                fd.close()
            is_package = kind == imp.PKG_DIRECTORY
            if is_package:
                pathname = os.path.join(pathname, "__init__.py")
                if not os.path.isfile(pathname):
                    return None
            elif kind != imp.PY_SOURCE:
                return None
            self._found[fullname] = (pathname, is_package)
            return self

        def load_module(self, fullname):
            if fullname in sys.modules:
                return sys.modules[fullname]
            pathname, is_package = self._found.pop(fullname)
            with open(pathname, "rb") as f:
                code = rewrite_source(f.read(), pathname)
            module = imp.new_module(fullname)
            module.__file__ = pathname
            module.__loader__ = self
            if is_package:
                module.__path__ = [os.path.dirname(pathname)]
                module.__package__ = fullname
            else:
                module.__package__ = fullname.rpartition(".")[0]
            self._sources[fullname] = pathname
            sys.modules[fullname] = module
            try:
                exec(code, module.__dict__)
            except BaseException:
                sys.modules.pop(fullname, None)
                raise
            return sys.modules[fullname]

        def is_package(self, fullname):
            return os.path.basename(self._sources[fullname]) == "__init__.py"

        def get_source(self, fullname):
            with open(self._sources[fullname], "rb") as f:
                return f.read()

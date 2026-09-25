from __future__ import absolute_import, division, print_function

import sys
import textwrap

import pytest

from cot_assert._rewrite import load_source

pytest_plugins = ["pytester"]

collect_ignore = []
try:
    import rpython.rtyper  # noqa: F401
except ImportError:
    collect_ignore.append("translated")
if sys.version_info[0] == 2:
    # vendored from pytest as it is, in Python 3 syntax
    collect_ignore.append("test_rewrite_coverage.py")
    collect_ignore.append("test_rewrite_fuzz.py")


@pytest.fixture
def rewritten():
    return lambda source, name="example": load_source(textwrap.dedent(source), name)


@pytest.fixture
def run_pytest(request, testdir):
    """Run pytest in a subprocess, with this plugin loaded one way or another."""
    if request.config.pluginmanager.has_plugin("cot_assert"):
        plugin = []  # installed: the entry point loads it
    else:
        plugin = ["-p", "cot_assert.pytest_plugin"]

    def run(*args):
        return testdir.runpytest_subprocess(
            "-p", "no:cacheprovider", *(plugin + list(args))
        )

    return run

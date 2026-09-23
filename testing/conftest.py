from __future__ import absolute_import, division, print_function

import textwrap

import pytest

from cot_assert._rewrite import load_source

pytest_plugins = ["pytester"]

try:
    import rpython.rtyper  # noqa: F401
except ImportError:
    collect_ignore = ["translated"]


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

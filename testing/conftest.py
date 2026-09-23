from __future__ import absolute_import, division, print_function

import textwrap

import pytest

from cot_assert._rewrite import load_source

try:
    import rpython.rtyper  # noqa: F401
except ImportError:
    collect_ignore = ["translated"]


@pytest.fixture
def rewritten():
    return lambda source, name="example": load_source(textwrap.dedent(source), name)

"""Assertion rewriting with a structured AssertionError."""

from __future__ import absolute_import, division, print_function

from ._entry import report_annotated
from ._error import AnnotatedAssertion, AssertSite, annotated
from ._hook import install, uninstall
from ._rewrite import rewrite_asserts, rewrite_source

# the public name, in tracebacks and pickles
AnnotatedAssertion.__module__ = __name__

__all__ = [
    "AnnotatedAssertion",
    "AssertSite",
    "annotated",
    "install",
    "report_annotated",
    "rewrite_asserts",
    "rewrite_source",
    "uninstall",
]

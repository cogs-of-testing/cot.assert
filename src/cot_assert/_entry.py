"""Making AnnotatedAssertion explanations visible from translated programs."""

from __future__ import absolute_import, division, print_function

import os

from ._error import AnnotatedAssertion
from ._rpy import we_are_translated


def report_annotated(func):
    """Wrap a translated entry point to print an escaping AnnotatedAssertion.

    Uncaught, RPython aborts with just the class name. The wrapper writes
    the explanation to stderr first and re-raises, so the abort still
    happens. On the host the traceback already shows it; nothing is written.
    """

    def entry_point(*args):
        try:
            return func(*args)
        # RPython rejects ``except`` on AssertionError or any subclass
        except Exception as exc:
            if we_are_translated() and isinstance(exc, AnnotatedAssertion):
                os.write(2, exc.render_plain() + "\n")
            raise

    entry_point.__name__ = "report_annotated_" + func.__name__
    return entry_point

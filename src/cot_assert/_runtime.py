"""Names the rewritten code calls; imported into rewritten modules."""

from __future__ import absolute_import, division, print_function

from ._error import AssertSite, annotated
from ._values import message as m
from ._values import value as v

__all__ = ["AssertSite", "fail", "m", "v"]


def fail(site, path, values, msg):
    return annotated(msg, site, path, values)

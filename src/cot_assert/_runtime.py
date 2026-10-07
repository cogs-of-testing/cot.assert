"""Names the rewritten code calls; imported into rewritten modules."""

from __future__ import absolute_import, division, print_function

from ._error import AssertSite, annotated
from ._rpy import rpy
from ._values import message as m
from ._values import value as v

__all__ = ["AssertSite", "fail", "m", "v"]


def fail(site, path, values, msg, dynamic=None):
    """The exception to raise; ``dynamic`` holds ``(slot, label, value)``
    for values evaluated on some runs only."""
    exc = annotated(msg, site, path, values)
    if dynamic is not None:
        for _, label, value in dynamic:
            exc.labels.append(label)
            exc.values.append(value)
        if not rpy.we_are_translated():
            exc.dynamic_slots = [slot for slot, _, _ in dynamic]
    return exc

"""Capturing values at the point an assert fails."""

from __future__ import absolute_import, division, print_function

from ._rpy import call_location, rpy


# Per call site, not per argtype: annotations that cannot be unioned share a
# knowntype (pointers to different structs, lists of different items, tuples
# of different lengths), and one graph for all of them does not annotate.
@call_location
def value(obj):
    """Host: the object itself. Translated: its RPython-level repr."""
    if not rpy.we_are_translated():
        return obj
    return rpy.repr(obj)


@call_location
def message(obj):
    """Host: the object itself. Translated: the str (or None) msg holds."""
    if not rpy.we_are_translated():
        return obj
    return rpy.message(obj)

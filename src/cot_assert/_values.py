"""Capturing values at the point an assert fails."""

from __future__ import absolute_import, division, print_function

from ._rpy import (
    KIND_BOOL,
    KIND_FLOAT,
    KIND_INT,
    KIND_NONE,
    KIND_STR,
    KIND_STR_OR_NONE,
    annotation_kind,
    float_repr,
    specialize,
    we_are_translated,
)


# Per call site, not per argtype: annotations that cannot be unioned share a
# knowntype (pointers to different structs, lists of different items, tuples
# of different lengths), and one graph for all of them does not annotate.
@specialize.call_location()
def value(obj):
    """Host: the object itself. Translated: its RPython-level repr."""
    if not we_are_translated():
        return obj
    # annotation_kind() is a constant, so each copy keeps one branch; obj is
    # only operated on where its annotation supports it
    kind = annotation_kind(obj)
    if kind == KIND_NONE:
        return "None"
    if kind == KIND_BOOL:
        if obj:
            return "True"
        return "False"
    if kind == KIND_INT:
        return str(obj)
    if kind == KIND_FLOAT:
        return float_repr(obj)
    if kind == KIND_STR_OR_NONE:
        if obj is None:
            return "None"
        return "'" + obj + "'"
    if kind == KIND_STR:
        return "'" + obj + "'"
    return "<object>"


@specialize.call_location()
def message(obj):
    """Host: the object itself. Translated: the str (or None) msg holds."""
    if not we_are_translated():
        return obj
    kind = annotation_kind(obj)
    if kind == KIND_NONE:
        return None
    if kind == KIND_STR or kind == KIND_STR_OR_NONE:
        return obj
    return value(obj)

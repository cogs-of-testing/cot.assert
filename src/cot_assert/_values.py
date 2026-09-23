"""Capturing values at the point an assert fails."""

from __future__ import absolute_import, division, print_function

from ._rpy import float_repr, specialize, we_are_translated


@specialize.argtype(0)
def value(obj):
    """Host: the object itself. Translated: its RPython-level repr."""
    if we_are_translated():
        return rpy_repr(obj)
    return obj


@specialize.argtype(0)
def rpy_repr(obj):
    if obj is None:
        return "None"
    if isinstance(obj, bool):
        if obj:
            return "True"
        return "False"
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, float):
        return float_repr(obj)
    if isinstance(obj, str):
        return "'" + obj + "'"
    return "<object>"

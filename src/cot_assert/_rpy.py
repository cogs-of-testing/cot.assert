"""rpython for code in the RPython subset, looked up when first needed.

pytest imports this package with its plugin, before any conftest has had a
chance to put rpython on sys.path; a lookup at import time would keep the
host stand-ins for the whole session. So code in the RPython subset reaches
rpython through ``rpy``: it is frozen, the flow space reads its attributes
while translating, when rpython is importable, and folds them to rpython's
own functions.
"""

from __future__ import absolute_import, division, print_function

import sys


def call_location(func):
    """rpython's ``specialize.call_location()``, which needs no import."""
    func._annspecialcase_ = "specialize:call_location"
    return func


def _host_we_are_translated():
    return False


class _RPython(object):
    def _freeze_(self):
        return True

    @property
    def we_are_translated(self):
        # translating imports rpython first; until then this is the host
        if "rpython" not in sys.modules:
            return _host_we_are_translated
        from rpython.rlib.objectmodel import we_are_translated

        return we_are_translated

    @property
    def repr(self):
        """``repr(obj)``: obj's repr as translated code can build it."""
        return _translated().rpy_repr

    @property
    def message(self):
        """``message(obj)``: a str or None as is, anything else as its repr."""
        return _translated().rpy_message


rpy = _RPython()

_cache = []


def _translated():
    if not _cache:
        _cache.append(_build())
    return _cache[0]


def _build():
    """The translated-only helpers; imports rpython, so only while translating.

    The repr is chosen by the rtyper from the final annotation. Chosen while
    annotating, the choice would be a constant that has to change when the
    argument generalizes (None to an instance, str to str-or-None), and the
    annotator never lets a constant change.
    """
    from rpython.annotator import model
    from rpython.rlib.rfloat import DTSF_ADD_DOT_0, formatd
    from rpython.rtyper.annlowlevel import hlstr, llstr
    from rpython.rtyper.extregistry import ExtRegistryEntry

    class Helpers(object):
        @staticmethod
        def rpy_repr(obj):
            raise NotImplementedError("translated code only")

        @staticmethod
        def rpy_message(obj):
            raise NotImplementedError("translated code only")

    def ll_bool_repr(b):
        if b:
            return llstr("True")
        return llstr("False")

    def ll_float_repr(f):
        # str() of an RPython float is "%f"; this matches the host's repr
        return llstr(formatd(f, "r", 0, DTSF_ADD_DOT_0))

    def ll_str_repr(s):
        if not s:
            return llstr("None")
        return llstr("'" + hlstr(s) + "'")

    def rtype_repr(hop, message):
        s_obj = hop.args_s[0]
        r_obj = hop.args_r[0]
        r_str = hop.r_result
        hop.exception_cannot_occur()
        if isinstance(s_obj, model.SomeNone):
            return hop.inputconst(r_str, None if message else "None")
        if isinstance(s_obj, model.SomeString):  # and SomeChar
            v_str = hop.inputarg(r_str, 0)
            if message:
                return v_str
            return hop.gendirectcall(ll_str_repr, v_str)
        # SomeBool subclasses SomeInteger, which subclasses SomeFloat
        if isinstance(s_obj, model.SomeBool):
            return hop.gendirectcall(ll_bool_repr, hop.inputarg(r_obj, 0))
        if isinstance(s_obj, model.SomeInteger):
            r_int = _word_sized(r_obj)
            return hop.gendirectcall(r_int.ll_str, hop.inputarg(r_int, 0))
        if isinstance(s_obj, model.SomeFloat):
            return hop.gendirectcall(ll_float_repr, hop.inputarg(r_obj, 0))
        return hop.inputconst(r_str, "<object>")

    def _word_sized(r_int):
        # ll_str does arithmetic, which types smaller than a machine word
        # do not support; rpython's own str() fails on them
        if getattr(r_int, "_opprefix", "") is not None:
            return r_int
        from rpython.rtyper.rint import signed_repr, unsigned_repr

        if r_int.lowleveltype._type.SIGNED:
            return signed_repr
        return unsigned_repr

    class ReprEntry(ExtRegistryEntry):
        _about_ = Helpers.rpy_repr

        def compute_result_annotation(self, s_obj):
            return model.SomeString()

        def specialize_call(self, hop):
            return rtype_repr(hop, message=False)

    class MessageEntry(ExtRegistryEntry):
        _about_ = Helpers.rpy_message

        def compute_result_annotation(self, s_obj):
            return model.SomeString(can_be_None=True)

        def specialize_call(self, hop):
            return rtype_repr(hop, message=True)

    return Helpers


__all__ = ["call_location", "rpy"]

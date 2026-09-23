"""Host view of an AnnotatedAssertion raised under RPython's llinterpreter."""

from __future__ import absolute_import, division, print_function

from ._error import AnnotatedAssertion, AssertSite


def from_llexception(interp, exc):
    """The AnnotatedAssertion inside an ``LLException``, or None.

    ``interp`` is the ``LLInterpreter`` that raised it; its rtyper knows the
    low-level layout of the class.
    """
    from rpython.rtyper.annlowlevel import hlstr
    from rpython.rtyper.lltypesystem import lltype
    from rpython.rtyper.rclass import getinstancerepr

    klass, inst = exc.args[0], exc.args[1]
    rtyper = interp.typer
    bookkeeper = rtyper.annotator.bookkeeper
    try:
        classdef = bookkeeper.getuniqueclassdef(AnnotatedAssertion)
    except Exception:
        return None
    r_inst = getinstancerepr(rtyper, classdef)
    vtable = r_inst.rclass.getvtable()
    if not _is_subclass(klass, vtable):
        return None
    inst = lltype.cast_pointer(r_inst.lowleveltype, inst)

    def text(ll):
        # a field that only ever holds one constant is Void, and reads back
        # as that host constant
        if ll is None or isinstance(ll, str):
            return ll
        return hlstr(ll) if ll else None

    def strlist(ll):
        if not ll:
            return []
        return [text(ll.ll_getitem_fast(i)) for i in range(ll.ll_length())]

    result = AnnotatedAssertion(
        text(inst.inst_msg),
        _host_site(rtyper, inst.inst_site),
        inst.inst_path,
        strlist(inst.inst_values),
    )
    result.labels = strlist(inst.inst_labels)
    return result


def _is_subclass(klass, vtable):
    # RPython vtables carry a [min, max] id range for subclass checks
    low, high = vtable.subclassrange_min, vtable.subclassrange_max
    return low <= klass.subclassrange_min < high


def _host_site(rtyper, ll_site):
    """The prebuilt host AssertSite behind a low-level one.

    Sites are prebuilt constants, so the host object exists; its fields that
    translated code never reads are not in the low-level struct at all.
    """
    from rpython.rtyper.lltypesystem import lltype
    from rpython.rtyper.rclass import getinstancerepr

    if not ll_site:
        return None
    classdef = rtyper.annotator.bookkeeper.getuniqueclassdef(AssertSite)
    r_site = getinstancerepr(rtyper, classdef)
    for host, ll in r_site.iprebuiltinstances.items():
        if lltype.cast_pointer(lltype.typeOf(ll_site), ll) == ll_site:
            return host
    raise LookupError("no prebuilt AssertSite for %r" % (ll_site,))

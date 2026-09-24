"""RPython primitives, or inert stand-ins when rpython is not importable.

Code in the RPython subset imports these from here, never from rpython
directly, so the package works on hosts without an rpython checkout.
"""

from __future__ import absolute_import, division, print_function

# what annotation_kind() tells apart; everything else renders as "<object>"
KIND_OTHER = 0
KIND_NONE = 1
KIND_BOOL = 2
KIND_INT = 3
KIND_FLOAT = 4
KIND_STR = 5
KIND_STR_OR_NONE = 6


def annotation_kind(obj):
    """Translated: a constant naming how ``obj``'s annotation is rendered.

    Decided from the annotation, not the value: isinstance() on a prebuilt
    constant sees the host object, which for a symbolic int is no int, so
    the same variable would change kind once it stops being constant.
    """
    return KIND_OTHER


try:
    from rpython.rlib.objectmodel import specialize, we_are_translated
    from rpython.rlib.rfloat import DTSF_ADD_DOT_0, formatd
    from rpython.rtyper.extregistry import ExtRegistryEntry

    def float_repr(x):
        # str() of an RPython float is "%f"; this matches the host's repr
        return formatd(x, "r", 0, DTSF_ADD_DOT_0)

    def _kind_of(s_obj):
        from rpython.annotator import model

        if isinstance(s_obj, model.SomeNone):
            return KIND_NONE
        if isinstance(s_obj, model.SomeBool):
            return KIND_BOOL
        if isinstance(s_obj, model.SomeInteger) and s_obj.knowntype is int:
            return KIND_INT
        if isinstance(s_obj, model.SomeFloat):
            return KIND_FLOAT
        if isinstance(s_obj, (model.SomeString, model.SomeChar)):
            if s_obj.can_be_None:
                return KIND_STR_OR_NONE
            return KIND_STR
        return KIND_OTHER

    class _AnnotationKindEntry(ExtRegistryEntry):
        _about_ = annotation_kind

        def compute_result_annotation(self, s_obj):
            return self.bookkeeper.immutablevalue(_kind_of(s_obj))

        def specialize_call(self, hop):
            from rpython.rtyper.lltypesystem import lltype

            hop.exception_cannot_occur()
            return hop.inputconst(lltype.Signed, _kind_of(hop.args_s[0]))

except ImportError:
    float_repr = repr

    def we_are_translated():
        return False

    class _Specialize(object):
        def __getattr__(self, name):
            def decorator_factory(*args, **kwargs):
                return lambda func: func

            return decorator_factory

    specialize = _Specialize()

__all__ = [
    "KIND_BOOL",
    "KIND_FLOAT",
    "KIND_INT",
    "KIND_NONE",
    "KIND_OTHER",
    "KIND_STR",
    "KIND_STR_OR_NONE",
    "annotation_kind",
    "float_repr",
    "specialize",
    "we_are_translated",
]

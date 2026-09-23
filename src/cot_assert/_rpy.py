"""RPython primitives, or inert stand-ins when rpython is not importable.

Code in the RPython subset imports these from here, never from rpython
directly, so the package works on hosts without an rpython checkout.
"""

from __future__ import absolute_import, division, print_function

try:
    from rpython.rlib.objectmodel import specialize, we_are_translated
    from rpython.rlib.rfloat import DTSF_ADD_DOT_0, formatd

    def float_repr(x):
        # str() of an RPython float is "%f"; this matches the host's repr
        return formatd(x, "r", 0, DTSF_ADD_DOT_0)

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

__all__ = ["float_repr", "specialize", "we_are_translated"]

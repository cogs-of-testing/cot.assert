"""Host-only rendering of an AnnotatedAssertion."""

from __future__ import absolute_import, division, print_function


def _saferepr(obj):
    try:
        return repr(obj)
    except Exception as e:
        return "<[%s raised in repr()] %s object>" % (
            type(e).__name__,
            type(obj).__name__,
        )


def render(exc):
    lines = []
    if exc.msg is not None:
        lines.append(str(exc.msg))
    if exc.site is not None:
        lines.append("assert " + exc.site.source)
    for label, obj in zip(exc.all_labels(), exc.values):
        lines.append(" where %s = %s" % (label, _saferepr(obj)))
    return "\n".join(lines)

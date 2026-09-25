"""Host-only rendering of an AnnotatedAssertion, in pytest's format.

The explanation mirrors what pytest's rewriter builds with %-templates at
rewrite time; here it is built from the site's shape and the values of the
failure path when it is needed. The formatting helpers follow
``_pytest.assertion.rewrite`` and ``_pytest.assertion.util`` (MIT licensed).
"""

from __future__ import absolute_import, division, print_function

import ast
import sys
import types

try:
    import reprlib
except ImportError:  # Python 2
    import repr as reprlib

PY2 = sys.version_info[0] == 2
if PY2:
    _string_types = (str, unicode)  # noqa: F821
else:
    _string_types = (str,)

DEFAULT_REPR_MAX_SIZE = 240


def _try_repr_or_str(obj):
    try:
        return repr(obj)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        return '%s("%s")' % (type(obj).__name__, obj)


def _format_repr_exception(exc, obj):
    try:
        exc_info = _try_repr_or_str(exc)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as inner_exc:
        exc_info = "unpresentable exception (%s)" % (_try_repr_or_str(inner_exc),)
    return "<[%s raised in repr()] %s object at 0x%x>" % (
        exc_info,
        type(obj).__name__,
        id(obj),
    )


def _ellipsize(s, maxsize):
    if len(s) > maxsize:
        i = max(0, (maxsize - 3) // 2)
        j = max(0, maxsize - 3 - i)
        return s[:i] + "..." + s[len(s) - j :]
    return s


class SafeRepr(reprlib.Repr):
    def __init__(self, maxsize):
        reprlib.Repr.__init__(self)
        self.maxstring = maxsize if maxsize is not None else 1000000000
        self.maxsize = maxsize

    def repr(self, x):
        try:
            s = reprlib.Repr.repr(self, x)
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:
            s = _format_repr_exception(exc, x)
        if self.maxsize is not None:
            s = _ellipsize(s, self.maxsize)
        return s

    def repr_instance(self, x, level):
        try:
            s = repr(x)
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:
            s = _format_repr_exception(exc, x)
        if self.maxsize is not None:
            s = _ellipsize(s, self.maxsize)
        return s

    def repr_dict(self, x, level):
        # insertion order, where the stdlib sorts
        n = len(x)
        if n == 0:
            return "{}"
        if level <= 0:
            return "{...}"
        pieces = []
        for i, key in enumerate(x):
            if i >= self.maxdict:
                pieces.append("...")
                break
            pieces.append(
                "%s: %s" % (self.repr1(key, level - 1), self.repr1(x[key], level - 1))
            )
        return "{" + ", ".join(pieces) + "}"


class Formatter(object):
    """The pieces of rendering a host may replace.

    The pytest plugin substitutes pytest's own comparison explanations and
    verbosity-dependent repr size.
    """

    maxsize = DEFAULT_REPR_MAX_SIZE

    def saferepr(self, obj):
        if isinstance(obj, types.MethodType):
            # for bound methods, skip redundant <bound method ...> information
            return obj.__name__
        if self.maxsize:
            text = SafeRepr(self.maxsize).repr(obj)
        else:
            text = _try_repr_or_str(obj)
        return text.replace("\n", "\\n")

    def reprcompare(self, op, left, right):
        """A multi-line explanation for ``left op right``, or None."""
        return None

    def format_assertmsg(self, obj):
        replaces = [("\n", "\n~")]
        if not isinstance(obj, _string_types):
            obj = self.saferepr(obj)
            replaces.append(("\\n", "\n~"))
        for old, new in replaces:
            obj = obj.replace(old, new)
        return obj

    def format_explanation(self, explanation):
        return "\n".join(_format_lines(_split_explanation(explanation)))


def _split_explanation(explanation):
    raw_lines = (explanation or "").split("\n")
    lines = [raw_lines[0]]
    for values in raw_lines[1:]:
        if values and values[0] in ["{", "}", "~", ">"]:
            lines.append(values)
        else:
            lines[-1] += "\\n" + values
    return lines


def _format_lines(lines):
    result = list(lines[:1])
    stack = [0]
    stackcnt = [0]
    for line in lines[1:]:
        if line.startswith("{"):
            if stackcnt[-1]:
                s = "and   "
            else:
                s = "where "
            stack.append(len(result))
            stackcnt[-1] += 1
            stackcnt.append(0)
            result.append(" +" + "  " * (len(stack) - 1) + s + line[1:])
        elif line.startswith("}"):
            stack.pop()
            stackcnt.pop()
            result[stack[-1]] += line[1:]
        else:
            stack[-1] += 1
            indent = len(stack) if line.startswith("~") else len(stack) - 1
            result.append("  " * indent + line[1:])
    return result


_formatter = Formatter()


def set_formatter(formatter):
    """Install the formatter ``render`` uses by default; returns the old one."""
    global _formatter
    previous, _formatter = _formatter, formatter
    return previous


def render(exc, formatter=None):
    formatter = formatter or _formatter
    site = exc.site
    values = exc.values
    parts = []
    if site is None or site.shape is None:
        if exc.msg is not None:
            parts.append(formatter.format_assertmsg(exc.msg_obj))
        if site is not None:
            parts.append("assert " + site.source)
        extra = list(zip(exc.all_labels(), values))
    else:
        slots, marks = site.paths[exc.path]
        explained = _Explainer(formatter, dict(zip(slots, values)), set(marks))
        explanation = explained.expl(site.shape)
        if exc.msg is not None:
            parts.append(formatter.format_assertmsg(exc.msg_obj))
            parts.append(">assert " + explanation)
        else:
            parts.append("assert " + explanation)
        extra = list(zip(exc.labels, values[len(slots) :]))
    for label, obj in extra:
        parts.append("~%s = %s" % (label, formatter.saferepr(obj)))
    text = "\n".join(parts)
    if text.startswith(("~", ">")):
        text = text[1:]
    return formatter.format_explanation(text)


_UNKNOWN = object()


class _Explainer(object):
    def __init__(self, formatter, values, marks):
        self.formatter = formatter
        self.values = values
        self.marks = marks

    def repr(self, slot):
        return self.formatter.saferepr(self.values[slot])

    def obj(self, shape):
        """The value behind an operand shape, or _UNKNOWN."""
        kind = shape[0]
        if kind == "const":
            try:
                return ast.literal_eval(shape[1])
            except ValueError:
                return _UNKNOWN
        if kind in ("name", "repr", "attr", "call", "binop", "unary"):
            return self.values.get(shape[1], _UNKNOWN)
        if kind == "compare" and shape[4] is not None:
            return self.values.get(shape[4], _UNKNOWN)
        return _UNKNOWN

    def expl(self, shape):
        return getattr(self, "expl_" + shape[0])(*shape[1:])

    def expl_const(self, source):
        obj = self.obj(("const", source))
        if obj is _UNKNOWN:
            return source
        return self.formatter.saferepr(obj)

    def expl_text(self, text):
        return text

    def expl_name(self, slot, name):
        if slot in self.values:
            return self.repr(slot)
        return name

    def expl_repr(self, slot):
        return self.repr(slot)

    def expl_attr(self, slot, value, attr):
        res = self.repr(slot)
        return "%s\n{%s = %s.%s\n}" % (res, res, self.expl(value), attr)

    def expl_method(self, obj, attr):
        return "%s.%s" % (self.expl(obj), attr)

    def expl_binop(self, slot, sym, left, right):
        return "(%s %s %s)" % (self.expl(left), sym, self.expl(right))

    def expl_unary(self, slot, pattern, operand):
        return pattern % (self.expl(operand),)

    def expl_call(self, slot, func, args):
        res = self.repr(slot)
        arglist = ", ".join(prefix + self.expl(arg) for prefix, arg in args)
        return "%s\n{%s = %s(%s)\n}" % (res, res, self.expl(func), arglist)

    def expl_boolop(self, node, is_or, operands):
        expls = [
            self.expl(shape)
            for i, shape in enumerate(operands)
            if ("bool", node, i) in self.marks
        ]
        return "(" + (" or " if is_or else " and ").join(expls) + ")"

    def expl_compare(self, node, syms, operands, result):
        # the first comparison known to fail, else the last one evaluated
        # (that is where pytest's _call_reprcompare stops)
        index = None
        for i in range(len(syms)):
            if ("cmp", node, i) in self.marks:
                index = i
                break
        if index is None and result is not None and result in self.values:
            if not self.values[result]:
                index = 0
        if index is None:
            index = len(syms) - 1
            while index > 0 and self.obj(operands[index + 1]) is _UNKNOWN:
                index -= 1
        left, right = operands[index], operands[index + 1]
        sym = syms[index]
        left_obj, right_obj = self.obj(left), self.obj(right)
        if left_obj is not _UNKNOWN and right_obj is not _UNKNOWN:
            custom = self.formatter.reprcompare(sym, left_obj, right_obj)
            if custom is not None:
                return custom
        return "%s %s %s" % (self.expl(left), sym, self.expl(right))

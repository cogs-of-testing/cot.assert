"""Expression source text for labels, identical on Python 2.7 and 3.x.

``ast.unparse`` does not exist on 2.7 and its output drifts between 3.x
releases; labels end up in prebuilt RPython constants and in test
expectations, so they come from here on every version.
"""

from __future__ import absolute_import, division, print_function

_BINOP = {
    "Add": ("+", 11),
    "Sub": ("-", 11),
    "Mult": ("*", 12),
    "MatMult": ("@", 12),
    "Div": ("/", 12),
    "FloorDiv": ("//", 12),
    "Mod": ("%", 12),
    "Pow": ("**", 14),
    "LShift": ("<<", 10),
    "RShift": (">>", 10),
    "BitOr": ("|", 7),
    "BitXor": ("^", 8),
    "BitAnd": ("&", 9),
}
_UNARY = {"Not": ("not ", 4), "Invert": ("~", 13), "USub": ("-", 13), "UAdd": ("+", 13)}
_CMP = {
    "Eq": "==",
    "NotEq": "!=",
    "Lt": "<",
    "LtE": "<=",
    "Gt": ">",
    "GtE": ">=",
    "Is": "is",
    "IsNot": "is not",
    "In": "in",
    "NotIn": "not in",
}
_BOOL = {"And": ("and", 3), "Or": ("or", 2)}
_ATOM = 16


def cmpop(op):
    return _CMP[type(op).__name__]


def binop(op):
    return _BINOP[type(op).__name__][0]


def unaryop(op):
    return _UNARY[type(op).__name__][0]


def unparse(node):
    return _unparse(node)[0]


def _wrap(node, minimum):
    text, prec = _unparse(node)
    if prec < minimum:
        return "(" + text + ")"
    return text


def _unparse(node):
    kind = type(node).__name__
    if kind == "Name":
        return node.id, _ATOM
    if kind in ("Constant", "NameConstant"):
        if node.value is Ellipsis:
            return "...", _ATOM
        return repr(node.value), _ATOM
    if kind == "Num":
        return repr(node.n), _ATOM
    if kind in ("Str", "Bytes"):
        return repr(node.s), _ATOM
    if kind == "Attribute":
        return _wrap(node.value, _ATOM) + "." + node.attr, _ATOM
    if kind == "Call":
        return _wrap(node.func, _ATOM) + "(" + ", ".join(_call_args(node)) + ")", _ATOM
    if kind == "Subscript":
        return _wrap(node.value, _ATOM) + "[" + _slice(node.slice) + "]", _ATOM
    if kind == "BinOp":
        op, prec = _BINOP[type(node.op).__name__]
        # ** is right associative, everything else left
        if op == "**":
            left, right = _wrap(node.left, prec + 1), _wrap(node.right, prec)
        else:
            left, right = _wrap(node.left, prec), _wrap(node.right, prec + 1)
        return left + " " + op + " " + right, prec
    if kind == "UnaryOp":
        op, prec = _UNARY[type(node.op).__name__]
        return op + _wrap(node.operand, prec), prec
    if kind == "Compare":
        parts = [_wrap(node.left, 6)]
        for op, comparator in zip(node.ops, node.comparators):
            parts.append(cmpop(op))
            parts.append(_wrap(comparator, 6))
        return " ".join(parts), 5
    if kind == "BoolOp":
        op, prec = _BOOL[type(node.op).__name__]
        return (" " + op + " ").join(_wrap(v, prec + 1) for v in node.values), prec
    if kind == "IfExp":
        return (
            _wrap(node.body, 2)
            + " if "
            + _wrap(node.test, 2)
            + " else "
            + _wrap(node.orelse, 1)
        ), 1
    if kind == "Lambda":
        return "lambda: ...", 0
    if kind == "Tuple":
        items = [unparse(e) for e in node.elts]
        if len(items) == 1:
            return "(" + items[0] + ",)", _ATOM
        return "(" + ", ".join(items) + ")", _ATOM
    if kind == "List":
        return "[" + ", ".join(unparse(e) for e in node.elts) + "]", _ATOM
    if kind == "Set":
        return "{" + ", ".join(unparse(e) for e in node.elts) + "}", _ATOM
    if kind == "Dict":
        items = []
        for k, v in zip(node.keys, node.values):
            if k is None:
                items.append("**" + _wrap(v, _ATOM))
            else:
                items.append(unparse(k) + ": " + unparse(v))
        return "{" + ", ".join(items) + "}", _ATOM
    if kind == "Starred":
        return "*" + _wrap(node.value, _ATOM), _ATOM
    if kind == "Repr":
        return "`" + unparse(node.value) + "`", _ATOM
    if kind in ("ListComp", "SetComp", "GeneratorExp", "DictComp"):
        return {"ListComp": "[...]", "SetComp": "{...}", "DictComp": "{...}"}.get(
            kind, "(...)"
        ), _ATOM
    if kind == "NamedExpr":
        return unparse(node.target) + " := " + _wrap(node.value, 1), 0
    return "<%s>" % kind, _ATOM


def _call_args(node):
    args = [unparse(a) for a in node.args]
    starargs = getattr(node, "starargs", None)
    if starargs is not None:
        args.append("*" + unparse(starargs))
    for kw in node.keywords:
        if kw.arg is None:
            args.append("**" + unparse(kw.value))
        else:
            args.append(kw.arg + "=" + unparse(kw.value))
    kwargs = getattr(node, "kwargs", None)
    if kwargs is not None:
        args.append("**" + unparse(kwargs))
    return args


def _slice(node):
    kind = type(node).__name__
    if kind == "Index":
        return _slice(node.value)
    if kind == "Slice":
        text = ""
        if node.lower is not None:
            text += unparse(node.lower)
        text += ":"
        if node.upper is not None:
            text += unparse(node.upper)
        if node.step is not None:
            text += ":" + unparse(node.step)
        return text
    if kind == "ExtSlice":
        return ", ".join(_slice(d) for d in node.dims)
    if kind == "Tuple" and node.elts:
        return ", ".join(_slice(e) for e in node.elts)
    return unparse(node)


__all__ = ["binop", "cmpop", "unaryop", "unparse"]

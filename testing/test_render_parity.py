"""Failure messages match pytest's own rewriter on the same source.

Each case is a function body; it runs once rewritten by cot_assert and once
by pytest, and both messages are compared. pytest's comparison hook and
config are switched off, so this checks the explanation structure; rich
comparison output is the pytest plugin's business.
"""

from __future__ import absolute_import, division, print_function

import ast
import sys
import textwrap

import pytest
from _pytest.assertion import rewrite as pytest_rewrite
from _pytest.assertion import util as pytest_util

from cot_assert import AnnotatedAssertion
from cot_assert._rewrite import rewrite_source

PRELUDE = """
class Obj(object):
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def __repr__(self):
        return "Obj(%r)" % (self.value,)


class BadRepr(object):
    def __repr__(self):
        raise ValueError("no")

GLOBAL_LIST = [1, 2]
"""


class BadRepr(object):
    """Marker for 'pass the prelude's BadRepr instance'."""


CASES = [
    ("x + 1 == y", (1, 5)),
    ("x == y", (1, 2)),
    ("x != y", (1, 1)),
    ("x", (0, None)),
    ("not x", (1, None)),
    ("-x == y", (1, 5)),
    ("x > 0 and y > 0", (1, -1)),
    ("x > 0 and y > 0", (-1, 1)),
    ("x > 0 or y > 0", (-1, -1)),
    ("x > 0 and (y > 0 or y < -5)", (1, -3)),
    ("x and y", (1, 0)),
    ("x or y", (0, 0)),
    ("0 < x < y", (0, 5)),
    ("0 < x < y", (3, 2)),
    ("x in y", (3, [1, 2])),
    ("x is None", (1, None)),
    ("len(x) == 3", ([1], None)),
    ("abs(x) == y", (-3, 2)),
    ("max(x, y) == 0", (1, 2)),
    ("sorted(x, reverse=True) == y", ([1, 2], [1, 2])),
    ("Obj(x).value == y", (1, 2)),
    ("x.value.value == 2", ("Obj(Obj(1))", None)),
    ("x[0] == y", ([1], 2)),
    ("x == 'a' * 300", ("b", None)),
    ("x == y", (BadRepr, 1)),
    ("x == [1, 2]", ([1], None)),
    ("x == y, 'plain message'", (1, 2)),
    ("x == y, 'two\\nlines'", (1, 2)),
    ("x == y, {'msg': x}", (1, 2)),
    ("x == y, 'with %s percent'", (1, 2)),
]

# Where the output differs from pytest on purpose; the reason is the value.
DIVERGENT = {
    # method calls keep their shape (no bound method temporary, which RPython
    # would have to annotate), so the method is shown as obj.name
    "x.get() == 2": (
        ("Obj(1)", None),
        "assert 1 == 2\n +  where 1 = Obj(1).get()",
    ),
    # names that are not local to the function are not tracked (under
    # RPython they would mostly be functions and classes); pytest shows the
    # repr of global data
    "x == GLOBAL_LIST": (
        ([1], None),
        "assert [1] == GLOBAL_LIST",
    ),
}


def _source(expr):
    return PRELUDE + textwrap.dedent(
        """
        def check(x, y):
            assert %s
        """
        % (expr,)
    )


def _arg(value, namespace):
    if value is BadRepr:
        return namespace["BadRepr"]()
    if isinstance(value, str) and value.startswith("Obj("):
        return eval(value, namespace)
    return value


def _run_cot(expr, args):
    namespace = {"__name__": "cot_case"}
    exec(rewrite_source(_source(expr), "<cot_case>"), namespace)
    args = [_arg(a, namespace) for a in args]
    with pytest.raises(AnnotatedAssertion) as excinfo:
        namespace["check"](*args)
    return str(excinfo.value)


def _run_pytest(expr, args):
    source = _source(expr)
    tree = ast.parse(source)
    if sys.version_info[0] == 2:
        pytest_rewrite.rewrite_asserts(tree)
    else:
        pytest_rewrite.rewrite_asserts(tree, source.encode())
    namespace = {"__name__": "pytest_case"}
    exec(compile(tree, "<pytest_case>", "exec"), namespace)
    args = [_arg(a, namespace) for a in args]
    with pytest.raises(AssertionError) as excinfo:
        namespace["check"](*args)
    return str(excinfo.value)


@pytest.fixture(autouse=True)
def _plain_pytest(monkeypatch):
    monkeypatch.setattr(pytest_util, "_reprcompare", None)
    monkeypatch.setattr(pytest_util, "_config", None, raising=False)


def _normalize(text):
    # the object ids in reprs of broken __repr__ differ between the runs
    import re

    return re.sub(r"object at 0x[0-9a-f]+", "object at 0x...", text)


PYTEST_4 = int(pytest.__version__.split(".")[0]) < 5


@pytest.mark.parametrize("expr, args", CASES)
def test_matches_pytest(expr, args):
    if PYTEST_4 and args[0] is BadRepr:
        pytest.skip("pytest 4.6 names its own SafeRepr as the failing object")
    assert _normalize(_run_cot(expr, args)) == _normalize(_run_pytest(expr, args))


@pytest.mark.parametrize("expr", sorted(DIVERGENT))
def test_known_divergence(expr):
    args, expected = DIVERGENT[expr]
    assert _run_cot(expr, args) == expected


# Operands whose values reach the comparison hook; the hook stands in for
# pytest_assertrepr_compare and shows exactly what it was passed.
HOOK_CASES = [
    ("x == y", ([1], [2])),
    ("x + [9] == y", ([1], [2, 9])),
    ("x == y + [9]", ([1, 9], [2])),
    ("-x == y", (1, 2)),
    ("x + 1 == y", (1, 5)),
    ("0 < x + 1 < y", (3, 2)),
    ("x[0] + x[1] == y", ([1, 2], 5)),
    ("len(x) + 1 == y", ([1], 5)),
]


def _hook(op, left, right):
    return "hook %r %s %r" % (left, op, right)


@pytest.mark.parametrize("expr, args", HOOK_CASES)
def test_comparison_hook_matches_pytest(expr, args, monkeypatch):
    from cot_assert import _render
    from cot_assert.pytest_plugin import PytestFormatter

    monkeypatch.setattr(pytest_util, "_reprcompare", _hook)
    monkeypatch.setattr(_render, "_formatter", PytestFormatter())
    assert _run_cot(expr, args) == _run_pytest(expr, args)

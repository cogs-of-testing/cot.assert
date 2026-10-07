"""Rewritten asserts behave as plain ones, on generated expressions.

Each expression runs twice, compiled as it is and rewritten, and both runs
must agree on the outcome (pass, AssertionError, or which other exception),
on every side effect in the order it happened, and on the names left bound.
A rewritten failure must also render. The expressions mix what makes
evaluation order observable: walrus, calls that trace, a method lookup that
traces, a global a call rebinds, and short-circuits of every kind.
"""

from __future__ import annotations

import ast
import textwrap
import warnings

import pytest

hypothesis = pytest.importorskip("hypothesis")
st = pytest.importorskip("hypothesis.strategies")

from cot_assert import AnnotatedAssertion  # noqa: E402
from cot_assert._rewrite import rewrite_asserts  # noqa: E402

PRELUDE = """
TRACE = []
G = 0

def f(*args, **kwargs):
    TRACE.append(("f", args, sorted(kwargs.items())))
    return args[-1] if args else len(kwargs)

def g():
    global G
    G += 1
    TRACE.append(("g", G))
    return G

def h():
    # at module level; check() has its own, rebinding its a
    global a
    a += 10
    TRACE.append(("h", a))
    return a

class O(object):
    def __init__(self, v):
        self.v = v

    @property
    def m(self):
        TRACE.append(("lookup", self.v))
        return self.take

    def take(self, x):
        TRACE.append(("take", self.v, x))
        return x

    def __repr__(self):
        return "O(%r)" % (self.v,)

obj = O(7)
L = [10, 20, 30]
D = {"k": 5}
"""

LEAVES = ["a", "b", "c", "0", "1", "2", "G", "obj.v", "L[0]", "D['k']", "g()", "h()"]
TARGETS = ["a", "b", "c"]


def _extend(child):
    two = st.tuples(child, child)
    return st.one_of(
        st.builds("({0[0]} {1} {0[1]})".format, two, st.sampled_from("+-*")),
        st.builds(
            "({0[0]} {1} {0[1]})".format,
            two,
            st.sampled_from(["==", "!=", "<", "<=", "is", "in"]),
        ),
        st.builds("({0[0]} < {0[1]} < {1})".format, two, child),
        st.builds("({0[0]} {1} {0[1]})".format, two, st.sampled_from(["and", "or"])),
        st.builds("(not {0})".format, child),
        st.builds("f({0})".format, child),
        st.builds("f({0[0]}, {0[1]})".format, two),
        st.builds("f(*[{0[0]}], {0[1]})".format, two),
        st.builds("f(k={0[0]}, j={0[1]})".format, two),
        st.builds("f(**{{'k': {0[0]}}}, j={0[1]})".format, two),
        st.builds("({1} := {0})".format, child, st.sampled_from(TARGETS)),
        st.builds("({0[0]} if {0[1]} else {1})".format, two, child),
        st.builds("obj.m({0})".format, child),
        st.builds("(obj := O({0})).v".format, child),
        st.builds("L[{0} % 3]".format, child),
        st.builds("[{0[0]}, {0[1]}]".format, two),
        st.builds("(1 // {0})".format, child),
        st.builds("(-{0})".format, child),
        st.builds(
            "({0[0]} {1} {0[1]})".format,
            two,
            st.sampled_from(["not in", "is not"]),
        ),
        st.builds("[x + {0[0]} for x in [{0[1]}]][0]".format, two),
        st.builds("(lambda: {0})()".format, child),
        st.builds("{{'k': {0[0]}, 'j': {0[1]}}}['k']".format, two),
        st.builds("f(*[{0[0]}], **{{'j': {0[1]}}})".format, two),
        st.builds("({0[0]} == {0[1]} in [{1}])".format, two, child),
    )


EXPRESSIONS = st.recursive(st.sampled_from(LEAVES), _extend, max_leaves=8)
INTS = st.integers(-3, 3)


def _source(expr, in_function):
    if in_function:
        body = (
            "def check(a, b, c):\n"
            "    def h():\n"
            "        nonlocal a\n"
            "        a += 10\n"
            "        TRACE.append(('h', a))\n"
            "        return a\n"
            "    assert %s\n"
            "    return a, b, c\n" % (expr,)
        )
    else:
        body = "a, b, c = A, B, C\nassert %s\n" % (expr,)
    return PRELUDE + body


def _run(expr, args, in_function, rewrite):
    source = _source(expr, in_function)
    tree = ast.parse(source)
    if rewrite:
        rewrite_asserts(tree)
    namespace = {"A": args[0], "B": args[1], "C": args[2]}
    with warnings.catch_warnings():
        # "x is 1" and the like: generated, and the same both ways
        warnings.simplefilter("ignore", SyntaxWarning)
        code = compile(tree, "<fuzz>", "exec")
    exc = None
    returned = None
    try:
        exec(code, namespace)
        if in_function:
            returned = namespace["check"](*args)
        else:
            returned = tuple(namespace[name] for name in "abc")
    except Exception as e:  # noqa: BLE001 - every outcome is compared
        exc = e
    if exc is None:
        outcome = ("passed",)
    elif isinstance(exc, AssertionError):
        outcome = ("AssertionError",)
    else:
        outcome = (type(exc).__name__, str(exc))
    observed = (outcome, namespace.get("TRACE"), namespace.get("G"), returned)
    return observed, exc


def check_expression(expr, args, in_function):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            # compile, not parse: some rules are the symbol table's
            compile(_source(expr, in_function), "<fuzz>", "exec")
    except SyntaxError:
        hypothesis.reject()
    plain, _ = _run(expr, args, in_function, rewrite=False)
    rewritten, exc = _run(expr, args, in_function, rewrite=True)
    assert rewritten == plain, "assert %s with a, b, c = %r" % (expr, args)
    if isinstance(exc, AnnotatedAssertion):
        text = str(exc)
        assert text.startswith("assert "), text
        exc.finalize("message")


@hypothesis.settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[hypothesis.HealthCheck.filter_too_much],
)
@hypothesis.given(
    expr=EXPRESSIONS,
    args=st.tuples(INTS, INTS, INTS),
    in_function=st.booleans(),
)
def test_rewritten_behaves_as_plain(expr, args, in_function):
    check_expression(expr, args, in_function)


# Found by the fuzzer; kept so that they run on every test run.
@pytest.mark.parametrize(
    "expr, args, in_function",
    [
        # an or ahead of more tests reported operands that had not run
        ("((a or obj.v) and a)", (0, 0, 0), True),
        ("((a or obj.v) and a)", (0, 0, 0), False),
        ("((a or [a, a]) and a)", (0, 0, 0), True),
        # the method was looked up after its argument ran
        ("obj.m(f(a))", (0, 0, 0), False),
    ],
)
def test_found_by_fuzzing(expr, args, in_function):
    check_expression(textwrap.dedent(expr), args, in_function)

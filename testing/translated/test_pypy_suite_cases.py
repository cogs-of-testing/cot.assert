"""Assert shapes from PyPy's rpython suite that rewritten code cannot translate yet.

Each case is the smallest function found that breaks a test in PyPy's rpython
suite once cot-assert rewrites it; the same source translates with plain
asserts. They are strict xfails: a fix turns them into failures that ask for
the marker to go.
"""

from __future__ import absolute_import, division, print_function

import pytest
from rpython.annotator.annrpython import RPythonAnnotator
from rpython.annotator.model import AnnotatorError, UnionError
from rpython.rtyper.test.test_llinterp import interpret

from cot_assert._rewrite import load_source

HEADER = """
import weakref
from rpython.rtyper.lltypesystem import lltype, llmemory

S1 = lltype.GcStruct("S1", ("x", lltype.Signed))
S2 = lltype.GcStruct("S2", ("y", lltype.Signed), ("z", lltype.Signed))

class B(object):
    pass

class C(B):
    pass

class W1(object):
    pass

class W2(object):
    pass
"""


def rewritten(source):
    return load_source(HEADER + source, "pypy_suite_case")


def knowntype_too_coarse(annotations):
    return pytest.mark.xfail(
        raises=UnionError,
        strict=True,
        reason="v() specializes on knowntype, which %s share" % annotations,
    )


@pytest.mark.xfail(
    raises=AssertionError,
    strict=True,
    reason="SomeTypeOf reaches `obj is None` in rpy_repr and bk.valueoftype(None)",
)
def test_type_is_narrows():
    f = rewritten(
        """
def f(x):
    assert type(x) is C
    return x
"""
    )["f"]
    s = RPythonAnnotator().build_types(f, [f.__globals__["B"]])
    assert s.classdef.name.endswith(".C")


@knowntype_too_coarse("SomePtr to different GcStructs")
def test_pointers_to_different_structs():
    f = rewritten(
        """
def f():
    p1 = lltype.malloc(S1)
    p2 = lltype.malloc(S2)
    assert p1
    assert p2
    return 0
"""
    )["f"]
    assert interpret(f, []) == 0


@knowntype_too_coarse("SomePtr and SomeInteriorPtr")
def test_interior_pointers():
    f = rewritten(
        """
BIG = lltype.GcStruct(
    "big",
    ("a", lltype.FixedSizeArray(lltype.Signed, 2)),
    ("b", lltype.FixedSizeArray(lltype.Signed, 3)),
)

def f():
    p = lltype.malloc(BIG)
    assert p.a
    assert p.b
    return 0
"""
    )["f"]
    assert interpret(f, []) == 0


@knowntype_too_coarse("SomeWeakRef to unrelated classes")
def test_weakrefs_to_unrelated_classes():
    f = rewritten(
        """
def f():
    a = W1()
    b = W2()
    ra = weakref.ref(a)
    rb = weakref.ref(b)
    assert ra() is a
    assert rb() is b
    return 0
"""
    )["f"]
    assert interpret(f, []) == 0


@knowntype_too_coarse("lists of different item types")
def test_lists_of_different_item_types():
    f = rewritten(
        """
def f(n):
    l1 = [n]
    l2 = [str(n)]
    assert l1 == [n]
    assert l2 == [str(n)]
    return 0
"""
    )["f"]
    assert interpret(f, [3]) == 0


@knowntype_too_coarse("tuples of different lengths")
def test_tuples_of_different_lengths():
    f = rewritten(
        """
def f(n):
    t1 = (n,)
    t2 = (n, n)
    assert t1 == (n,)
    assert t2 == (n, n)
    return 0
"""
    )["f"]
    assert interpret(f, [3]) == 0


@pytest.mark.xfail(
    raises=AssertionError,
    strict=True,
    reason="isinstance() is folded on the symbolic constant, then on a plain int",
)
def test_symbolic_constant_then_variable():
    f = rewritten(
        """
from rpython.rtyper.lltypesystem import llarena

def g():
    return llarena.round_up_for_allocation(llmemory.sizeof(S1))

PREBUILT = g()

def check(size):
    assert size == llmemory.sizeof(lltype.Signed)

def f():
    check(PREBUILT)
    check(g())
    return 0
"""
    )["f"]
    assert interpret(f, []) == 0


@pytest.mark.xfail(
    raises=UnionError,
    strict=True,
    reason="SomeAddress has knowntype object; isinstance(obj, float) is not folded",
)
def test_address():
    f = rewritten(
        """
def f():
    p = lltype.malloc(S1)
    adr = llmemory.cast_ptr_to_adr(p)
    assert adr
    return 0
"""
    )["f"]
    assert interpret(f, []) == 0


@pytest.mark.xfail(
    raises=AnnotatorError,
    strict=True,
    reason="a module bound by a local import is captured as a value",
)
def test_module_imported_in_function():
    f = rewritten(
        """
def f(n):
    from rpython.rtyper.lltypesystem import rffi
    assert rffi.cast(lltype.Signed, n) == n
    return 0
"""
    )["f"]
    assert interpret(f, [3]) == 0


@pytest.mark.xfail(
    raises=UnionError,
    strict=True,
    reason="the message object becomes the msg field, which other sites make str",
)
def test_non_string_message():
    f = rewritten(
        """
def f(n):
    assert n > 0, "positive"
    assert n < 10, [n]
    return 0
"""
    )["f"]
    assert interpret(f, [3]) == 0


@pytest.mark.xfail(
    raises=AssertionError,
    strict=True,
    reason="removeassert only matches the prebuilt plain AssertionError",
)
def test_remove_asserts_removes_rewritten_asserts():
    from rpython.translator.backendopt.removeassert import remove_asserts
    from rpython.translator.translator import TranslationContext, graphof

    fn = rewritten(
        """
def fn(n):
    assert n > 0
    return n - 1
"""
    )["fn"]
    t = TranslationContext()
    t.buildannotator().build_types(fn, [int])
    t.buildrtyper().specialize()
    graph = graphof(t, fn)
    remove_asserts(t, [graph])
    ops = [op.opname for block in graph.iterblocks() for op in block.operations]
    assert "direct_call" not in ops


@pytest.mark.xfail(
    raises=AssertionError,
    strict=True,
    reason="the C backend aborts early only on AssertionError itself, not subclasses",
)
def test_compiled_failure_is_fatal_where_first_caught(capsys):
    from rpython.translator.c.test.test_genc import compile

    fn = rewritten(
        """
import os

def g(n):
    assert n != 1

def fn(n):
    try:
        g(n)
    finally:
        os.write(2, "finally ran\\n")
    return n
"""
    )["fn"]
    compiled = compile(fn, [int])
    capsys.readouterr()
    compiled(1, expected_exception_name="AnnotatedAssertion")
    assert "finally ran" not in capsys.readouterr().out

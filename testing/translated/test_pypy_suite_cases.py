"""Assert shapes from PyPy's rpython suite that broke rewritten code.

Each case is the smallest function found that broke a test in PyPy's rpython
suite once cot-assert 0.1.0 rewrote it; the same source translates with plain
asserts. The ones still open are strict xfails; see docs/design/rpython.md.
"""

from __future__ import absolute_import, division, print_function

import pytest
from rpython.annotator.annrpython import RPythonAnnotator
from rpython.rtyper.llinterp import LLException
from rpython.rtyper.test.test_llinterp import get_interpreter, interpret
from rpython.translator.translator import TranslationContext, graphof

from cot_assert._llexc import from_llexception
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


def test_type_is_narrows():
    """SomeTypeOf crashes `is None` in the annotator."""

    f = rewritten(
        """
def f(x):
    assert type(x) is C
    return x
"""
    )["f"]
    s = RPythonAnnotator().build_types(f, [f.__globals__["B"]])
    assert s.classdef.name.endswith(".C")


def test_pointers_to_different_structs():
    """Pointers to different structs share a knowntype."""

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


def test_interior_pointers():
    """Pointers and interior pointers share a knowntype."""

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


def test_weakrefs_to_unrelated_classes():
    """Weakrefs to unrelated classes share a knowntype."""

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


def test_lists_of_different_item_types():
    """Lists of different items share a knowntype."""

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


def test_tuples_of_different_lengths():
    """Tuples of different lengths share a knowntype."""

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


def test_symbolic_constant_then_variable():
    """isinstance() on the prebuilt symbolic is False, on the variable True."""

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
    # the llinterpreter cannot compare symbolic sizes; PyPy's test compiles
    t = TranslationContext()
    t.buildannotator().build_types(f, [])
    t.buildrtyper().specialize()


def test_address():
    """SomeAddress has knowntype object, like anything unknown."""

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


def test_module_imported_in_function():
    """RPython cannot represent a module."""

    f = rewritten(
        """
def f(n):
    from rpython.rtyper.lltypesystem import rffi
    assert rffi.cast(lltype.Signed, n) == n
    return 0
"""
    )["f"]
    assert interpret(f, [3]) == 0


def test_non_string_message():
    """The msg field is str, whatever the assert passed."""

    f = rewritten(
        """
def f(n):
    assert n > 0, "positive"
    assert n < 10, [n]
    return 0
"""
    )["f"]
    interp, graph = get_interpreter(f, [0])
    assert interp.eval_graph(graph, [3]) == 0
    messages = []
    for n in (0, 11):
        with pytest.raises(LLException) as excinfo:
            interp.eval_graph(graph, [n])
        messages.append(from_llexception(interp, excinfo.value).msg)
    assert messages == ["positive", "<object>"]


def _removes_assertion_subclasses():
    """Whether this rpython's removeassert drops failure paths that build
    an AssertionError subclass, not only raises of the prebuilt instance."""
    from rpython.translator.backendopt import removeassert

    return hasattr(removeassert, "always_fails_assertion")


@pytest.mark.xfail(
    not _removes_assertion_subclasses(),
    raises=AssertionError,
    strict=True,
    reason="rpython's removeassert only matches the prebuilt AssertionError",
)
def test_remove_asserts_removes_rewritten_asserts():
    from rpython.translator.backendopt.removeassert import remove_asserts

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


def test_compiled_failure_propagates_like_other_exceptions(capsys):
    """Unlike AssertionError itself, not fatal where first caught.

    RPython's C backend aborts on the spot only for exactly AssertionError;
    a subclass runs finally blocks and aborts with its own name. Accepted;
    see docs/design/rpython.md.
    """
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
    assert "finally ran" in capsys.readouterr().out


# found running PyPy's rpython suite under 0.2.0


def test_sized_integer():
    """SomeInteger subclasses SomeFloat; USHORT has no arithmetic."""

    f = rewritten(
        """
from rpython.rlib.rarithmetic import byteswap
from rpython.rtyper.lltypesystem import rffi

def f():
    swapped = byteswap(rffi.cast(rffi.USHORT, 0x0102))
    assert rffi.cast(lltype.Signed, swapped) == 0x0201
    return 0
"""
    )["f"]
    assert interpret(f, []) == 0


def test_value_generalizing_to_another_kind():
    """PyPy's test_nongc.py::test_isinstance; smaller variants pass."""
    f = rewritten(
        """
from rpython.rlib.objectmodel import free_non_gc_object

class A(object):
    _alloc_flavor_ = "raw"

class RawB(A):
    pass

class RawC(RawB):
    pass

def f(i):
    if i == 0:
        o = None
    elif i == 1:
        o = A()
    elif i == 2:
        o = RawB()
    else:
        o = RawC()
    res = 100 * isinstance(o, A) + 10 * isinstance(o, RawB) + isinstance(o, RawC)
    if i == 0:
        pass
    elif i == 1:
        assert isinstance(o, A)
        free_non_gc_object(o)
    elif i == 2:
        assert isinstance(o, RawB)
        free_non_gc_object(o)
    else:
        assert isinstance(o, RawC)
        free_non_gc_object(o)
    return res
"""
    )["f"]
    RPythonAnnotator().build_types(f, [int])


CHECK_LATE_RPYTHON = """
import sys
import cot_assert
from cot_assert._rewrite import load_source
sys.path.append(sys.argv[1])
from rpython.annotator.annrpython import RPythonAnnotator
f = load_source("def f(n):\\n    assert n > 0\\n    return n\\n", "late")["f"]
RPythonAnnotator().build_types(f, [int])
"""


def test_rpython_importable_only_after_cot_assert(tmpdir):
    """PyPy's CI made rpython importable only after the plugin had loaded."""
    import os
    import subprocess
    import sys

    import rpython

    checkout = os.path.dirname(os.path.dirname(os.path.abspath(rpython.__file__)))
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        entry
        for entry in env.get("PYTHONPATH", "").split(os.pathsep)
        if os.path.abspath(entry) != checkout
    )
    script = tmpdir.join("check.py")
    script.write(CHECK_LATE_RPYTHON)
    proc = subprocess.Popen(
        [sys.executable, str(script), checkout],
        env=env,
        cwd=str(tmpdir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = proc.communicate()[0].decode("utf-8", "replace")
    assert proc.returncode == 0, output


def test_values_render_by_final_annotation():
    """The rtyper picks each repr from the annotation the value ends with."""
    f = rewritten(
        """
from rpython.rlib.rarithmetic import r_longlong, r_uint
from rpython.rtyper.lltypesystem import rffi

from cot_assert import annotated

def f(n):
    text = None
    if n > 1:
        text = "t"
    if n > 0:
        raise (
            annotated("values")
            .annotate("small", rffi.cast(rffi.USHORT, n))
            .annotate("unsigned", r_uint(n))
            .annotate("long", r_longlong(-n))
            .annotate("flag", n > 10)
            .annotate("half", n / 2.0)
            .annotate("char", chr(65 + n))
            .annotate("text", text)
            .annotate("nothing", None)
            .annotate("box", W1())
        )
    return 0
"""
    )["f"]
    interp, graph = get_interpreter(f, [0])
    with pytest.raises(LLException) as excinfo:
        interp.eval_graph(graph, [1])
    exc = from_llexception(interp, excinfo.value)
    assert exc.values == [
        "1",
        "1",
        "-1",
        "False",
        "0.5",
        "'B'",
        "None",
        "None",
        "<object>",
    ]

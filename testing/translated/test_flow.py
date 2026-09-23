"""Rewriter output, pushed through the RPython flow space.

Each case is function source with asserts. The rewriter turns it into code
objects; the same functions then run on the host, under the llinterpreter and
compiled to C, so a case checks the rewriter's behaviour and that its output
is RPython at the same time.
"""

from __future__ import absolute_import, division, print_function

import pytest
from rpython.rtyper.llinterp import LLException
from rpython.rtyper.test.test_llinterp import get_interpreter

from cot_assert._llexc import from_llexception
from cot_assert._rewrite import load_source
from flow_cases import FAILING, PASSING, SOURCE


@pytest.fixture(scope="module")
def entry():
    return load_source(SOURCE, "flow_example")["entry"]


@pytest.fixture(scope="module")
def ll_interp(entry):
    # one annotation for all cases: every shape has to unify in one program
    return get_interpreter(entry, [0, 0, 0])


@pytest.mark.parametrize("args, result", PASSING)
def test_llinterp_passing(ll_interp, args, result):
    interp, graph = ll_interp
    assert interp.eval_graph(graph, list(args)) == result


@pytest.mark.parametrize("args, path, msg, labels, values", FAILING)
def test_llinterp_failing(ll_interp, args, path, msg, labels, values):
    interp, graph = ll_interp
    with pytest.raises(LLException) as excinfo:
        interp.eval_graph(graph, list(args))
    exc = from_llexception(interp, excinfo.value)
    assert exc is not None
    assert (exc.path, exc.msg, exc.all_labels(), exc.values) == (
        path,
        msg,
        labels,
        values,
    )


@pytest.fixture(scope="module")
def compiled(entry):
    from rpython.translator.c.test.test_genc import compile

    from cot_assert import report_annotated

    return compile(report_annotated(entry), [int, int, int])


@pytest.mark.parametrize("args, result", PASSING)
def test_compiled_passing(compiled, args, result):
    assert compiled(*args) == result


@pytest.mark.parametrize("args, path, msg, labels, values", FAILING)
def test_compiled_failing_prints_explanation(
    compiled, capsys, args, path, msg, labels, values
):
    capsys.readouterr()
    compiled(*args, expected_exception_name="AnnotatedAssertion")
    # compile() echoes the program's stderr to our stdout
    stderr = capsys.readouterr().out.split("--- stderr ---")[1]
    for label, value in zip(labels, values):
        assert " where %s = %s\n" % (label, value) in stderr
    if msg is not None:
        assert msg + "\n" in stderr


def _keeps_assertion_subclass_init():
    """Whether this rpython runs __init__ of AssertionError subclasses."""
    from rpython.annotator.classdesc import ClassDesc

    class Probe(AssertionError):
        pass

    desc = ClassDesc.__new__(ClassDesc)
    desc.pyobj = Probe
    return not desc.is_builtin_exception_class()


@pytest.mark.skipif(
    not _keeps_assertion_subclass_init(),
    reason="rpython skips AssertionError subclass __init__ (unpatched)",
)
def test_constructor_translates_on_patched_rpython():
    from cot_assert import AnnotatedAssertion

    def direct(n):
        if n > 3:
            raise AnnotatedAssertion("direct").annotate("n", n)
        return n

    interp, graph = get_interpreter(direct, [0])
    assert interp.eval_graph(graph, [2]) == 2
    with pytest.raises(LLException) as excinfo:
        interp.eval_graph(graph, [7])
    exc = from_llexception(interp, excinfo.value)
    assert (exc.msg, exc.all_labels(), exc.values) == ("direct", ["n"], ["7"])

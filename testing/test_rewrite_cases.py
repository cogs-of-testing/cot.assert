from __future__ import absolute_import, division, print_function

import pytest

from cot_assert import AnnotatedAssertion
from cot_assert._rewrite import load_source
from flow_cases import FAILING, PASSING, SOURCE


@pytest.fixture(scope="module")
def entry():
    return load_source(SOURCE, "flow_example")["entry"]


@pytest.mark.parametrize("args, result", PASSING)
def test_host_passing(entry, args, result):
    assert entry(*args) == result


@pytest.mark.parametrize("args, path, msg, labels, values", FAILING)
def test_host_failing_keeps_objects(entry, args, path, msg, labels, values):
    with pytest.raises(AnnotatedAssertion) as excinfo:
        entry(*args)
    exc = excinfo.value
    assert (exc.path, exc.msg, exc.all_labels()) == (path, msg, labels)
    # host values are the objects; only the rendering matches RPython's
    assert len(exc.values) == len(values)

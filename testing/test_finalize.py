from __future__ import absolute_import, division, print_function

import gc
import pickle
import sys
import weakref

import pytest

from cot_assert import AnnotatedAssertion

SOURCE = """
class Tracked(object):
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return "Tracked(%r)" % (self.value,)


def check(x, msg=None):
    if msg is None:
        assert Tracked(x).value == 2
    else:
        assert Tracked(x).value == 2, msg
"""

EXPLANATION = (
    "assert 1 == 2\n +  where 1 = Tracked(1).value\n +    where Tracked(1) = Tracked(1)"
)


@pytest.fixture
def module(rewritten):
    return rewritten(SOURCE, "finalize_example")


def failure(module, *args):
    """The raised AnnotatedAssertion, detached from its traceback."""
    try:
        module["check"](*args)
    except AnnotatedAssertion as exc:
        caught = exc
    else:
        pytest.fail("did not raise")
    if sys.version_info[0] == 2:
        sys.exc_clear()  # noqa: F821 - the traceback keeps the frame alive
    else:
        caught.__traceback__ = None
    return caught


def test_str_renders_lazily_before_finalize(module):
    exc = failure(module, 1)
    assert exc.rendered is None
    assert str(exc) == EXPLANATION
    # slots in evaluation order: x, Tracked(x), Tracked(x).value
    assert exc.values[1].value == 1


def test_finalize_into_notes(module):
    exc = failure(module, 1).finalize()
    assert exc.__notes__ == [EXPLANATION]
    assert (exc.values, exc.site, exc.args) == (None, None, ())
    assert str(exc) == ""


def test_finalize_into_notes_keeps_message_as_str(module):
    exc = failure(module, 1, 42).finalize()
    assert exc.__notes__ == ["42\nassert 1 == 2\n" + EXPLANATION.split("\n", 1)[1]]
    assert str(exc) == "42"


def test_finalize_into_message(module):
    exc = failure(module, 1).finalize("message")
    assert exc.args == (EXPLANATION,)
    assert str(exc) == EXPLANATION
    assert not getattr(exc, "__notes__", None)


def test_finalize_is_idempotent(module):
    exc = failure(module, 1).finalize()
    exc.finalize()
    assert exc.__notes__ == [EXPLANATION]


def test_unknown_mode_leaves_exception_untouched(module):
    exc = failure(module, 1)
    with pytest.raises(ValueError):
        exc.finalize("loud")
    assert exc.values is not None


def test_finalize_releases_tracked_objects(module):
    exc = failure(module, 1)
    ref = weakref.ref(exc.values[1])
    gc.collect()
    assert ref() is not None
    exc.finalize()
    gc.collect()
    assert ref() is None


@pytest.mark.parametrize("mode", ["notes", "message"])
def test_finalized_exception_pickles(module, mode):
    exc = failure(module, 1).finalize(mode)
    clone = pickle.loads(pickle.dumps(exc))
    assert type(clone) is AnnotatedAssertion
    assert str(clone) == str(exc)
    assert clone.rendered == EXPLANATION
    assert getattr(clone, "__notes__", None) == getattr(exc, "__notes__", None)


def test_manual_annotations_render_after_the_site():
    exc = AnnotatedAssertion("too big").annotate("n", 5).annotate("half", 2.5)
    assert str(exc) == "too big\n  n = 5\n  half = 2.5"


def test_manual_annotations_without_message():
    exc = AnnotatedAssertion().annotate("n", 5)
    assert str(exc) == "n = 5"

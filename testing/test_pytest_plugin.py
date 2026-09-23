from __future__ import absolute_import, division, print_function

import os
import sys

import pytest

KIND = """
import pytest

def test_kind():
    with pytest.raises(AssertionError) as excinfo:
        assert 1 == 2
    print("KIND=" + type(excinfo.value).__name__)
"""


def test_off_by_default(testdir, run_pytest):
    testdir.makepyfile(test_kind=KIND)
    result = run_pytest("-s")
    result.stdout.fnmatch_lines(["*KIND=AssertionError*"])


def test_enabled_by_option(testdir, run_pytest):
    testdir.makepyfile(test_kind=KIND)
    result = run_pytest("-s", "--cot-assert")
    result.stdout.fnmatch_lines(["*KIND=AnnotatedAssertion*"])


def test_enabled_by_ini(testdir, run_pytest):
    testdir.makeini("[pytest]\ncot_assert = true\n")
    testdir.makepyfile(test_kind=KIND)
    result = run_pytest("-s")
    result.stdout.fnmatch_lines(
        ["cot_assert: rewriting asserts (finalize into message)", "*KIND=Annotated*"]
    )


def test_failure_shows_pytest_comparison(testdir, run_pytest):
    testdir.makepyfile(
        test_diff="""
        def test_lists():
            left = [1, 2, 3]
            assert left == [1, 5, 3]
        """
    )
    result = run_pytest("--cot-assert")
    result.stdout.fnmatch_lines(
        [
            "E       *AnnotatedAssertion: assert [[]1, 2, 3] == [[]1, 5, 3]",
            "E*At index 1 diff: 2 != 5*",
        ]
    )
    assert result.ret == 1


def test_failure_with_message_and_where(testdir, run_pytest):
    testdir.makepyfile(
        test_msg="""
        def double(x):
            return x * 2

        def test_msg():
            assert double(2) == 5, "doubling is off"
        """
    )
    result = run_pytest("--cot-assert")
    result.stdout.fnmatch_lines(
        [
            "E       *AnnotatedAssertion: doubling is off",
            "E       assert 4 == 5",
            "E        +  where 4 = double(2)",
        ]
    )


def test_conftest_is_rewritten(testdir, run_pytest):
    testdir.makeconftest(
        """
        import pytest

        @pytest.fixture
        def checked():
            value = 3
            assert value == 4
        """
    )
    testdir.makepyfile(test_fix="def test_uses(checked):\n    pass\n")
    result = run_pytest("--cot-assert")
    result.stdout.fnmatch_lines(["E       *AnnotatedAssertion: assert 3 == 4"])
    assert result.ret == 1


@pytest.mark.skipif(
    sys.version_info < (3, 11), reason="traceback shows notes from 3.11 on"
)
def test_finalize_into_notes(testdir, run_pytest):
    testdir.makeini("[pytest]\ncot_assert = true\ncot_assert_finalize = notes\n")
    testdir.makepyfile(test_notes="def test_it():\n    x = 1\n    assert x == 2\n")
    result = run_pytest()
    result.stdout.fnmatch_lines(
        ["E       cot_assert.AnnotatedAssertion", "E       assert 1 == 2"]
    )


def test_invalid_finalize_mode(testdir, run_pytest):
    testdir.makeini("[pytest]\ncot_assert = true\ncot_assert_finalize = loud\n")
    testdir.makepyfile(test_kind=KIND)
    result = run_pytest()
    result.stderr.fnmatch_lines(["*cot_assert_finalize must be one of*loud*"])
    assert result.ret != 0


@pytest.mark.skipif(
    sys.version_info[0] == 2 or sys.dont_write_bytecode,
    reason="needs pytest's bytecode cache",
)
def test_cache_name_differs_from_pytest(testdir, run_pytest):
    from cot_assert._hook import CACHE_TAG

    testdir.makepyfile(test_kind=KIND)
    run_pytest("--cot-assert").assert_outcomes(passed=1)
    run_pytest().assert_outcomes(passed=1)
    cached = sorted(os.listdir(str(testdir.tmpdir.join("__pycache__"))))
    ours = [name for name in cached if CACHE_TAG in name]
    theirs = [name for name in cached if CACHE_TAG not in name]
    assert len(ours) == 1
    assert len(theirs) == 1

"""The examples in docs/examples.md run and print what the page shows.

Each section of the page is one example. ``<!-- file: NAME -->`` before a
fenced block writes that block to NAME; ``<!-- run: COMMAND -->`` runs
``pytest ...`` or ``python ...`` on those files, and every fenced block after
it, up to the next comment or heading, has to appear in the output as a run
of consecutive lines (trailing whitespace ignored). A failure line, starting
with ``E``, has to match exactly; any other line, such as pytest's summary,
only has to be contained in its output line.
"""

from __future__ import absolute_import, division, print_function

import io
import os
import re
import shlex

import pytest

DOC = os.path.join(os.path.dirname(__file__), os.pardir, "docs", "examples.md")

# the outputs shown are pytest 9's, whose format differs from earlier ones
pytestmark = pytest.mark.skipif(
    int(pytest.__version__.split(".")[0]) < 9,
    reason="docs/examples.md shows pytest 9's output",
)

DIRECTIVE = re.compile(r"^<!-- (file|run): (.+) -->$")


class Example(object):
    def __init__(self, title):
        self.title = title
        self.files = []  # (name, content)
        self.runs = []  # (command, [expected block, ...])


def parse(text):
    examples = []
    current = None
    target = None  # ("file", name) or ("run", expected blocks)
    lines = iter(text.splitlines())
    for line in lines:
        if line.startswith("#"):
            current = None
            target = None
            if line.startswith("## "):
                current = Example(line[3:])
                examples.append(current)
            continue
        match = DIRECTIVE.match(line)
        if match:
            kind, arg = match.groups()
            if kind == "file":
                target = ("file", arg)
            else:
                blocks = []
                current.runs.append((arg, blocks))
                target = ("run", blocks)
            continue
        if line.startswith("```") and line != "```":
            block = []
            for inner in lines:
                if inner == "```":
                    break
                block.append(inner)
            if target is None:
                continue
            if target[0] == "file":
                current.files.append((target[1], "\n".join(block) + "\n"))
                target = None
            else:
                target[1].append(block)
    return [example for example in examples if example.runs]


with io.open(DOC, encoding="utf-8") as f:
    EXAMPLES = parse(f.read())


def test_every_example_is_found():
    assert len(EXAMPLES) == 8
    for example in EXAMPLES:
        assert example.files, example.title
        assert all(blocks for _, blocks in example.runs), example.title


def _contains(output_lines, expected):
    expected = [line.rstrip() for line in expected]
    for start in range(len(output_lines) - len(expected) + 1):
        found = output_lines[start : start + len(expected)]
        if all(_matches(want, got) for want, got in zip(expected, found)):
            return True
    return False


def _matches(want, got):
    # failure lines exactly, the summary line without its timing
    if want.startswith("E"):
        return want == got
    return want in got


@pytest.mark.parametrize(
    "example", EXAMPLES, ids=[re.sub(r"\W+", "-", e.title) for e in EXAMPLES]
)
def test_example(example, testdir, run_pytest):
    for name, content in example.files:
        testdir.tmpdir.join(name).write(content)
    for command, blocks in example.runs:
        program, args = command.split(" ", 1)[0], shlex.split(command)[1:]
        if program == "pytest":
            result = run_pytest(*args)
        else:
            assert program == "python", command
            result = testdir.runpython(testdir.tmpdir.join(args[0]))
        output = [line.rstrip() for line in result.outlines]
        for block in blocks:
            assert _contains(output, block), "%s: %s\n%s" % (
                command,
                "\n".join(block),
                "\n".join(output),
            )

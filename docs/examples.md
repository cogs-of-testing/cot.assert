# cot-assert compared with pytest's assertion rewriting

## What it is for

pytest rewrites `assert` statements so that a failure explains itself.
cot-assert does the same job with a different split of the work:

- **The rewriter records, the host renders.** A failed assert raises
  `AnnotatedAssertion`, an `AssertionError` subclass that keeps the
  asserted source and the values it failed on. The explanation text is
  built only when someone asks for it (`str(exc)`, `render()`,
  `finalize()`), so the host decides how and where it is shown. Under
  pytest that is pytest's own formatting and comparison hooks, so a diff
  looks the same.
- **One rewriter for Python 2.7, Python 3 and RPython.** The rewritten
  code also passes through the RPython translator, so RPython code and its
  test suites get explained asserts, under the llinterpreter and compiled
  to C. That is what most of the deliberate differences below come from;
  `docs/design/rpython.md` has the details.
- **Python's evaluation order.** A rewritten assert evaluates its operands
  in the order plain Python does, also when an operand rebinds a name.
- **Usable without pytest.** `cot_assert.install()` rewrites matching
  modules in any program.

Under pytest it is a plugin that stays off until enabled with
`--cot-assert` or `cot_assert = true` in the ini file.

Every example below is run by `testing/test_docs_examples.py`, once with
plain pytest and once with `--cot-assert`, and the output shown is checked
against what they print. The output is pytest 9's; only the `E` lines of
the failure are shown.

## What stays the same

Comparisons, calls, messages and `and`/`or` read as they do with pytest.
The difference is the exception type, `cot_assert.AnnotatedAssertion`.

<!-- file: test_same.py -->
```python
def double(x):
    return x * 2


def test_call():
    assert double(2) == 5, "doubling is off"


def test_lists():
    left = [1, 2, 3]
    assert left == [1, 5, 3]


def test_and():
    x, y = 1, -1
    assert x > 0 and y > 0
```

<!-- run: pytest -->
```text
E       AssertionError: doubling is off
E       assert 4 == 5
E        +  where 4 = double(2)
```

```text
E       assert [1, 2, 3] == [1, 5, 3]
E
E         At index 1 diff: 2 != 5
E         Use -v to get more diff
```

```text
E       assert (1 > 0 and -1 > 0)
```

<!-- run: pytest --cot-assert -->
```text
E       cot_assert.AnnotatedAssertion: doubling is off
E       assert 4 == 5
E        +  where 4 = double(2)
```

```text
E       cot_assert.AnnotatedAssertion: assert [1, 2, 3] == [1, 5, 3]
E
E         At index 1 diff: 2 != 5
E         Use -v to get more diff
```

```text
E       cot_assert.AnnotatedAssertion: assert (1 > 0 and -1 > 0)
```

The list diff comes from pytest's `pytest_assertrepr_compare` hook, which
cot-assert calls with the same operands pytest's rewriter would.

## Method calls are shown on one line

pytest explains a method call in two steps, the call and the bound method.
cot-assert shows the receiver, the method and the arguments together, as
pytest-dev/pytest#14817 proposes for pytest.

<!-- file: test_method.py -->
```python
class Counter:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def __repr__(self):
        return "Counter(%r)" % (self.value,)


def test_method():
    counter = Counter(1)
    assert counter.get() == 2
```

<!-- run: pytest -->
```text
E       assert 1 == 2
E        +  where 1 = get()
E        +    where get = Counter(1).get
```

<!-- run: pytest --cot-assert -->
```text
E       cot_assert.AnnotatedAssertion: assert 1 == 2
E        +  where 1 = Counter(1).get()
```

## Subscripts and conditional expressions are broken down

pytest shows neither the container a value was looked up in nor which
branch of a conditional expression ran. cot-assert shows both, as
pytest-dev/pytest#14815 and pytest-dev/pytest#14816 propose for pytest.
Slices are not broken down.

<!-- file: test_subscript.py -->
```python
def test_subscript():
    data = {"a": 1}
    assert data["a"] == 2


def test_conditional():
    flag = True
    assert (0 if flag else 1) == 1
```

<!-- run: pytest -->
```text
E       assert 1 == 2
```

```text
E       assert 0 == 1
```

<!-- run: pytest --cot-assert -->
```text
E       cot_assert.AnnotatedAssertion: assert 1 == 2
E        +  where 1 = {'a': 1}['a']
```

```text
E       cot_assert.AnnotatedAssertion: assert 0 == 1
E        +  where 0 = (... if True else ...)
```

## Operands are evaluated in Python's order

An assert must pass or fail exactly as it would without rewriting. pytest's
rewriter reads a name when it builds the explanation, which can be after a
later operand has rebound it. Run without rewriting (`--assert=plain`),
both asserts below fail.

<!-- file: test_order.py -->
```python
class Box:
    def __init__(self, value):
        self.value = value

    def take(self, other):
        return self.value

    def __repr__(self):
        return "Box(%r)" % (self.value,)


def identity(x):
    return x


def test_rebound_name():
    value = 1
    assert value == identity(value := 3)


def test_rebound_receiver():
    box = Box(1)
    assert box.take(identity(box := None)) == 2
```

With pytest, `test_rebound_name` passes, although `1 == 3` is false. In
`test_rebound_receiver` the method was called on `Box(1)`, but the
explanation names `None.take`:

<!-- run: pytest -->
```text
1 failed, 1 passed
```

```text
E       assert 1 == 2
E        +  where 1 = take(None)
E        +    where take = None.take
E        +    and   None = identity(None)
```

cot-assert fails both, and explains them with the values that were used:

<!-- run: pytest --cot-assert -->
```text
E       cot_assert.AnnotatedAssertion: assert 1 == 3
E        +  where 3 = identity(3)
```

```text
E       cot_assert.AnnotatedAssertion: assert 1 == 2
E        +  where 1 = Box(1).take(None)
E        +    where None = identity(None)
```

## Module-level names are shown by name

This difference is a cost. cot-assert only tracks names local to the
function: under RPython, module-level names are mostly functions and
classes, which it cannot pass around as values. pytest shows the value of
a module-level name, and passes it to the comparison hook; cot-assert shows
the name, and so has no diff to show for it. Attributes of a module-level
name, such as `math.pi`, are shown as with pytest. Bind the expected value
to a local name to get the diff back.

<!-- file: test_global.py -->
```python
EXPECTED = {"a": 1, "b": 2}


def test_global():
    got = {"a": 1, "b": 3}
    assert got == EXPECTED
```

<!-- run: pytest -->
```text
E       AssertionError: assert {'a': 1, 'b': 3} == {'a': 1, 'b': 2}
E
E         Omitting 1 identical items, use -vv to show
E         Differing items:
E         {'b': 3} != {'b': 2}
E         Use -v to get more diff
```

<!-- run: pytest --cot-assert -->
```text
E       cot_assert.AnnotatedAssertion: assert {'a': 1, 'b': 3} == EXPECTED
```

## The exception keeps the values

Code that catches the failure can read what the assert saw, instead of
parsing text. `site.source` is the asserted expression, `msg` the message,
and `all_labels()` and `values` the tracked sub-expressions and their
values, in the order they were evaluated.

<!-- file: test_values.py -->
```python
import pytest


def test_values():
    with pytest.raises(AssertionError) as excinfo:
        items = [1, 2]
        assert len(items) == 3, "need three"
    exc = excinfo.value
    assert exc.site.source == "len(items) == 3"
    assert exc.msg == "need three"
    assert list(zip(exc.all_labels(), exc.values)) == [
        ("items", [1, 2]),
        ("len(items)", 2),
    ]
```

<!-- run: pytest -->
```text
E       AttributeError: 'AssertionError' object has no attribute 'site'
```

<!-- run: pytest --cot-assert -->
```text
1 passed
```

When a test fails, the plugin calls `exc.finalize()` before pytest reports
it: the explanation is rendered once, while pytest's comparison hook is
still set, and the values are dropped, so the report no longer keeps the
tested objects alive and the exception pickles.

## The explanation as a note

By default the explanation becomes the exception's message, as with pytest.
`cot_assert_finalize = notes` adds it as a PEP 678 note instead, and leaves
the message to what the assert itself said.

<!-- file: pytest.ini -->
```ini
[pytest]
cot_assert = true
cot_assert_finalize = notes
```

<!-- file: test_notes.py -->
```python
def test_notes():
    items = [1, 2]
    assert len(items) == 3
```

<!-- run: pytest -->
```text
E       cot_assert.AnnotatedAssertion
E       assert 2 == 3
E        +  where 2 = len([1, 2])
```

## Without pytest

`cot_assert.install()` rewrites the modules imported after it whose name
matches one of the patterns. Without a host, `str()` of the exception
renders the explanation with cot-assert's own formatting.

<!-- file: shapes.py -->
```python
def check(items):
    assert len(items) == 3, "need three"
```

<!-- file: run.py -->
```python
import cot_assert

cot_assert.install(["shapes"])

import shapes  # noqa: E402

try:
    shapes.check([1, 2])
except AssertionError as exc:
    print(type(exc).__name__)
    print(exc)
```

<!-- run: python run.py -->
```text
AnnotatedAssertion
need three
assert 2 == 3
 +  where 2 = len([1, 2])
```

Without `install()`, the same call raises a plain `AssertionError` whose
message is only `need three`.

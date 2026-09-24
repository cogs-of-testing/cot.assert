# Rewritten asserts under RPython

Findings from `testing/translated/test_flow.py`, which feeds rewriter output
through the flow space, the llinterpreter and the C backend (PyPy2.7 image,
PyPy checkout on `rpython-py3-import-m1`), and from running PyPy's rpython
suite under cot-assert 0.1.0; `testing/translated/test_pypy_suite_cases.py`
keeps a reproducer for each difference found there.

## What the emitted code has to respect

- **One type per temporary.** Every sub-expression gets its own temporary.
  pytest resets its temporaries to `None`, which makes an int temporary a
  union of int and None that does not annotate; here each is deleted at the
  end of the block that assigned it, reached only once the assert passed.
- **Short-circuits as nested `if`s.** Each exit that can fail raises with only
  the values evaluated on that path; the site keeps one label list per path.
- **Values become str at the raise.** Behind `we_are_translated()` (folded
  to True by the flow space) `v()` returns an RPython-level repr, so
  `values` is a list of str when translated and the objects themselves on
  the host. The message goes through `m()`, which keeps a str and renders
  anything else like `v()`: the `msg` field is str.
- **One `v()` graph per call site** (`specialize.call_location()`).
  `argtype` keys on `knowntype`, which annotations that do not union share:
  pointers to different structs, pointers and interior pointers, weakrefs to
  unrelated classes, lists of different items, tuples of different lengths.
  The cost is a small graph per tracked value, on failure paths only.
- **The repr is picked from the annotation.** `annotation_kind()` is an
  extregistry function that folds to a constant per annotation: None, bool,
  int, float, str (or str-or-None), or other, which renders `<object>`
  without touching the value. `isinstance()` does not work for this: see
  below.
- **Names bound by `import` are not tracked**; RPython cannot represent a
  module, so passing one to `v()` fails to annotate.
- **Float repr** goes through `rfloat.formatd(x, "r", 0, DTSF_ADD_DOT_0)`;
  `str()` of an RPython float is `"%f"`.

## `AssertionError` subclasses are special

`ClassDesc.is_builtin_exception_class()` counts every subclass of
`AssertionError` as a built-in exception (a workaround for the py lib's own
`AssertionError`). For such classes the annotator

- skips `__init__` entirely, whatever arguments are passed, and
- allows no instance attributes unless the class lists them in `_attrs_`.

The rule began as `self.pyobj is py.code._AssertionError` and was widened
to `issubclass(..., AssertionError)` in pypy commit 6a53fd84de, "fix compiling
an empty module". Neither rpython nor pypy defines an `AssertionError`
subclass outside tests.

Both ways are supported:

- **Unpatched rpython:** `AnnotatedAssertion` declares `_attrs_`, and code
  builds it with the `annotated()` factory, which calls `init_fields()` on an
  instance made with no arguments. The rewriter always emits this.
- **Patched rpython** (`rpython/annotator/classdesc.py` narrowed back to the
  py lib's class, matched by module name, since touching
  `py.code._AssertionError` imports the deprecated `compiler` package):
  `AnnotatedAssertion(msg)` works directly. The test for it skips on an
  unpatched checkout.

## Reading the result back

- Under the llinterpreter, `cot_assert._llexc.from_llexception` turns the
  `LLException` into a host `AnnotatedAssertion` with str values.
- Fields of the prebuilt `AssertSite` that translated code never reads are not
  in the low-level struct; the host site is recovered from the instance
  repr's `iprebuiltinstances`.
- A field that only ever holds one constant is `Void` and reads back as the
  host constant.
- Compiled to C, an uncaught `AnnotatedAssertion` aborts with
  `Fatal RPython error: AnnotatedAssertion` and nothing else.
  `report_annotated(entry_point)` writes `render_plain()` to fd 2 first and
  re-raises. It catches `Exception` and checks `isinstance`, because the flow
  space rejects `except` on `AssertionError` or any subclass.

## Workarounds an rpython fix could undo

These live in cot-assert only because of how rpython behaves; each could go
once rpython changes, and the reproducers would keep passing.

| workaround | rpython behaviour behind it | undo once |
|---|---|---|
| `annotated()` and `_attrs_` instead of the constructor | every `AssertionError` subclass counts as built-in (above) | `classdesc.py` is narrowed back to the py lib's class |
| `annotation_kind()` instead of `isinstance()` in the repr | `x is None` on `SomeTypeOf` (from `type(x)`) asserts in `bk.valueoftype(None)`, `signature.py`, also without cot-assert; `isinstance()` on a prebuilt symbolic int folds on the host object, which is no int, so the same variable flips from not-int to int once it stops being constant ("annotation got narrower"); `SomeAddress` has `knowntype` `object`, so `isinstance(adr, float)` does not fold | all three are fixed; even then the extregistry kind is the simpler dispatch |
| `specialize.call_location()` for `v()`, `m()`, `annotate()` | `specialize.argtype` keys on `knowntype` only | a specialization keyed on the full annotation or its low-level type exists (`arglltype` is mix-level only) |

Not rpython's to fix, and staying: deleting temporaries, not tracking
imported names, `msg` as text.

## Still open

Both have strict xfails in `test_pypy_suite_cases.py`.

- **`remove_asserts` does not remove rewritten asserts.**
  `backendopt.removeassert` (on at `--opt=3`, `size`, `mem`) only drops a
  link that raises the prebuilt plain `AssertionError` instance straight from
  the block that tests the condition. A rewritten assert raises an
  `AnnotatedAssertion` it allocates, after the `v()` calls on the failure
  path. An rpython fix would follow the failing exit to a raise of any
  `AssertionError` subclass and drop the whole path. PyPy's
  `translator/backendopt/test/test_removeassert.py` fails on it.
- **A failed rewritten assert is not fatal where it is first caught.** The
  exception transformer checks `etype != AssertionError` by identity, both
  for the debug-mode `ll_assert` in `rpyexc_raise` and for
  `debug_catch_exception`, so an `AnnotatedAssertion` propagates like any
  exception: `finally` blocks run and the abort names
  `AnnotatedAssertion`. An rpython fix would check the subclass range.
  PyPy's `test_standalone.py::test_assertion_error_debug`,
  `test_assertion_error_nondebug` and `test_exception.py::test_assert` fail
  on it; they also expect the name `AssertionError`.

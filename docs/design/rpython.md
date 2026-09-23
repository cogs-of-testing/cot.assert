# Rewritten asserts under RPython

Findings from `testing/translated/test_flow.py`, which feeds rewriter output
through the flow space, the llinterpreter and the C backend (PyPy2.7 image,
PyPy checkout on `rpython-py3-import-m1`).

## What the emitted code has to respect

- **One type per temporary.** Every sub-expression gets its own temporary and
  none is reset to `None` afterwards; pytest's reset makes an int temporary a
  union of int and None, which does not annotate.
- **Short-circuits as nested `if`s.** Each exit that can fail raises with only
  the values evaluated on that path; the site keeps one label list per path.
- **Values become str at the raise.** `v()` is `specialize.argtype(0)`; behind
  `we_are_translated()` (folded to True by the flow space) it returns an
  RPython-level repr, so `values` is a list of str when translated and the
  objects themselves on the host.
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

## `remove_asserts` does not remove rewritten asserts

`backendopt.removeassert` (on at `--opt=3`, `size`, `mem`) only drops raises
of the prebuilt plain `AssertionError` instance. Rewritten asserts allocate an
`AnnotatedAssertion`, so they survive where plain asserts would be removed.

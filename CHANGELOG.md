# Changelog

## Unreleased

Fixes for what running PyPy's rpython suite under cot-assert turned up.

- Translated `v()` is specialized per call site and picks the repr from the
  annotation: asserts on pointers, interior pointers, weakrefs, lists,
  tuples, addresses, `type(x)` and symbolic sizes translate.
- Names a function binds by `import` are shown by name, not tracked: RPython
  cannot pass a module to `v()`.
- Temporaries are deleted once an assert passes, so they no longer keep the
  tested objects alive.
- `msg` is always text: a message that is not a string no longer crashes
  pytest 4.6 with `INTERNALERROR`, and translates. The object stays in
  `msg_obj` for the explanation.
- Documented: rewritten asserts are removed by `remove_asserts` only with a
  patched rpython, and a failing one is not fatal where first caught.

## 0.1.0

First release.

- Assert rewriter whose output the RPython flow space accepts: rich asserts
  in RPython code and its test suites, under the llinterpreter and compiled
  to C (`report_annotated()` prints the explanation before the abort).
- `AnnotatedAssertion`, an `AssertionError` subclass that keeps the values
  an assert failed on, renders pytest's explanation on demand, and
  `finalize()`s into a note or the message, dropping the values.
- `annotated()` builds one from RPython code; the constructor works there
  too with an rpython whose annotator no longer treats every
  `AssertionError` subclass as built-in.
- Import hook: `cot_assert.install(match)`.
- pytest plugin for pytest 4.6 and current pytest, off until enabled with
  `--cot-assert` or `cot_assert = true`.
- One source for Python 2.7 and 3.9 to 3.14.

# Changelog

## 0.2.3

Cached rewrites are checked against the source's contents and follow a
moved source, as pytest main does for its own.

- A cache file holds a hash of the source instead of its mtime and size
  (a PEP 552 checked-hash pyc). An edit that keeps the size within the same
  second is no longer served from the cache, and a fresh checkout or a
  restored cache no longer invalidates every file.
- A source moved together with its `__pycache__` (a renamed directory, the
  same tree mounted elsewhere) keeps its cache, and its code points at the
  new path. Under pytest 4.6, which takes a conftest's `__file__` from the
  cached code, such a tree failed with `ImportMismatchError`.
- The rewriter digest in the cache name also covers the runtime rewritten
  code calls into (`_runtime`, `_error`, `_values`), not only the rewriter.
- Writing a cache file removes the ones earlier cot-assert versions left
  for the same source and interpreter.
- Under pytest, cot-assert replaces pytest's import hook with its own
  instead of patching `rewrite_asserts` and `PYC_TAIL` in pytest's rewriter.
  It selects modules by pytest's rules and shares the cache files of the
  standalone hook, which now also caches on Python 2.

## 0.2.2

- A comparison whose operand is an arithmetic or unary expression
  (`x + [9] == y`, `-x == y`) passes the operand's value to pytest's
  comparison hook, as pytest's rewriter does. It passed nothing, so such
  asserts showed no diff. The value was already captured; only the
  explanation dropped it, so translated code is unchanged.

## 0.2.1

Fixes for what running PyPy's full rpython suite under 0.2.0 turned up.

- Translated values are rendered by the rtyper from their final
  annotation. Integers of every size render as numbers: 0.2.0 sent `r_uint`,
  `r_longlong`, `USHORT` and the like to the float repr, which failed to
  type. A value whose annotation generalizes (None to an instance, str to
  str-or-None) no longer fails with "annotation got narrower".
- rpython is looked up while translating, not when cot-assert is imported,
  so it may become importable after the pytest plugin has loaded (a
  conftest that puts it on `sys.path`, a relative `PYTHONPATH`).

## 0.2.0

Fixes for what running PyPy's rpython suite under cot-assert 0.1.0 turned
up. Each case has a reproducer in
`testing/translated/test_pypy_suite_cases.py`.

- Translated values are captured per call site, and the repr is picked from
  the annotation, not by `isinstance()`. Asserts now translate on pointers
  to different structs, interior pointers, weakrefs to unrelated classes,
  lists of different item types, tuples of different lengths, addresses,
  `type(x)` and symbolic sizes. `AnnotatedAssertion.annotate()` is
  specialized the same way.
- A name a function binds with `import` is shown by name, not tracked:
  RPython cannot pass a module to a function.
- Temporaries are deleted once an assert passes, so they no longer keep the
  tested objects alive, for example across `del x; gc.collect()` in a test.
- `AnnotatedAssertion.msg` is always text or None. A message that is not a
  string (`assert x, [1, 2]`) crashed pytest 4.6 with `INTERNALERROR`, and
  did not translate. The message object is in the new `msg_obj`, for the
  explanation.
- `backendopt.remove_asserts` (`--opt=3`, `size`, `mem`) removes rewritten
  asserts only with a patched rpython. A failing rewritten assert is not
  fatal where it is first caught, unlike a plain `AssertionError`; this is
  accepted. See `docs/design/rpython.md`.

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

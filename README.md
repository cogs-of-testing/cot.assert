# cot-assert

Assertion rewriting that raises a structured `AnnotatedAssertion`, for Python
2.7, Python 3.9+ and RPython. Intended as a drop-in replacement for pytest's
assertion rewriting on current pytest and on pytest 4.6.

Pre-alpha; nothing is published yet.

## With pytest

Installing the package registers a pytest plugin that stays off until
enabled:

```ini
[pytest]
cot_assert = true
# where a failed assert's explanation goes: message (default) or notes
cot_assert_finalize = message
```

or `pytest --cot-assert`. On Python 2.7, where it runs from source, load it
with `-p cot_assert.pytest_plugin`.

pytest still decides which modules are rewritten (test files, conftests,
`pytest.register_assert_rewrite`) and caches them under a separate name;
cot_assert does the rewriting, and failures render through pytest's own
comparison hooks. Failures show as `AnnotatedAssertion` instead of
`AssertionError`. `--assert=plain` turns rewriting off for both.

## Without pytest

```python
import cot_assert

cot_assert.install(["mypackage", "test_*"])
```

rewrites modules imported afterwards whose name matches.

Under pytest, cot-assert replaces pytest's import hook with its own
instead of patching `rewrite_asserts` and `PYC_TAIL` in pytest's rewriter.
It selects modules by pytest's rules and shares the cache files of the
standalone hook, which now also caches on Python 2.

A source moved together with its `__pycache__` (a renamed directory, the
same tree mounted elsewhere) keeps its cache, and its code points at the
new path. Under pytest 4.6, which takes a conftest's `__file__` from the
cached code, such a tree failed with `ImportMismatchError`.

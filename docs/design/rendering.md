# Rendering and finalizing

## Explanations are built on demand

pytest's rewriter formats a %-template while the assert fails. Here the
rewriter only records what the template needs, and the host builds the text
when it is asked for (`str(exc)`, `render()`, `finalize()`):

- **shape** — a tree of tuples mirroring the asserted expression: `name`,
  `attr`, `call`, `method`, `binop`, `unary`, `subscript`, `ifexp`,
  `compare`, `boolop`, `boolexp`, `const`, `text` and `repr` nodes. Tracked
  nodes refer to a *slot*.
- **paths** — one entry per failure exit: the slots evaluated on the way
  there, in the order their values are passed to `fail()`, and marks saying
  which boolean operands ran and which comparison is known to have failed.

Both live on the prebuilt `AssertSite`. Translated code never reads them, so
RPython never annotates them; it uses `path_labels` and `render_plain()`.

`_render.render()` walks the shape with the failing path's values and
produces pytest's format. `saferepr`, `format_assertmsg`,
`format_explanation` and the comparison hook sit on a `Formatter`, which a
host can replace with `set_formatter()`; the pytest plugin will route
`reprcompare` to `pytest_assertrepr_compare`.

`testing/test_render_parity.py` runs every case through both rewriters and
compares the messages, with pytest's comparison hook and config switched off.
They match on pytest 9 and on pytest 4.6, except that pytest 4.6 names its
own `SafeRepr` when an object's `__repr__` raises. A second set of cases
switches a stand-in hook on, to check it is passed the same operand values
as under pytest: a `binop` or `unary` operand passes its result, which its
temporary already holds, not the text of the expression.

`testing/test_rewrite_coverage.py` is pytest's coverage matrix for its
rewriter, vendored from the series that ends in pytest-dev/pytest#14916 and
run against this one; `testing/test_rewrite_fuzz.py` runs generated asserts
both plain and rewritten and compares everything observable.

## Evaluation order

A rewritten assert evaluates every operand into a temporary as soon as its
own operands are, which is Python's order, with three exceptions:

- **A name** is left in place, so it is read only when the expression
  around it is assembled. When anything evaluated before that can run code
  (a call, an operator, an attribute, a walrus operator), the name is read
  into a temporary first: a call can rebind it through `global` or
  `nonlocal`, a walrus operator directly.
- **A method** is looked up before its arguments run, as in Python; when an
  argument can run code, the bound method goes into a temporary for that.
  It is only called, never passed to `v()`, so RPython does not have to
  render it.
- **Operands of `and` and `or`** after the first run on some runs only. At
  the top of an assert each gets its own failure exit, but only where
  nothing is tested after them. Elsewhere, and wherever `and`/`or` is a
  value (`not (a and b)`, `f(a or b)`), their values are appended as they
  are evaluated to a list, `(slot, label, v(value))` each, which `fail()`
  adds to the labels and values; slots every exit passes would read
  temporaries that were never assigned. Temporaries cannot be preset to
  `None` instead: RPython keeps each at one type.

## Deliberate differences from pytest

- **Method calls** show on one line, `where 1 = Obj(1).get()`, as
  pytest-dev/pytest#14817 does; pytest 9 adds a line for the bound method.
- **Subscripts** show the container and key, `where 1 = {'a': 1}['a']`, as
  pytest-dev/pytest#14815 does; slices do not. So does the condition of a
  conditional expression, `where 0 = (... if True else ...)`, as
  pytest-dev/pytest#14816 does.
- **Names not local to the function** are not tracked: under RPython they
  are mostly functions and classes. pytest shows the repr of global data;
  here the name stays. Names a function binds by `import` count as not
  local: they are modules, which RPython cannot pass to `v()`.
- **Temporaries are deleted** once the assert passes, not reset to `None`,
  so they neither keep the tested objects alive nor change type.

## finalize()

`msg` is always text or None, because pytest reads it as text as soon as
it catches the exception, before the plugin can finalize it. A message that
is not a string is shown as `str()` shows it there, and kept in `msg_obj`
for the explanation, which formats it the way pytest does.

`exc.finalize(mode)` renders once and keeps only text: `values` and `site`
become None and `msg_obj` becomes `msg`. With `mode="notes"` the explanation
becomes a PEP 678 note (`add_note` on 3.11+, `__notes__` before); with
`mode="message"` it becomes `args[0]`, for hosts that do not show notes.
A finalized exception pickles (a custom `__reduce__`, since `BaseException`'s
passes `args` to `__init__`) and no longer keeps the tested objects alive.

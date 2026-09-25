# Rendering and finalizing

## Explanations are built on demand

pytest's rewriter formats a %-template while the assert fails. Here the
rewriter only records what the template needs, and the host builds the text
when it is asked for (`str(exc)`, `render()`, `finalize()`):

- **shape** — a tree of tuples mirroring the asserted expression: `name`,
  `attr`, `call`, `method`, `binop`, `unary`, `compare`, `boolop`, `const`,
  `text` and `repr` nodes. Tracked nodes refer to a *slot*.
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

## Deliberate differences from pytest

- **Method calls** keep the `obj.method(...)` shape, because a bound method
  in a temporary is a value RPython would have to annotate. The explanation
  shows `where 1 = Obj(1).get()` where pytest adds a line for the bound
  method.
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

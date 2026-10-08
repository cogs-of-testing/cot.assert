PEP: 9999
Title: Annotated Assertions
Author: Ronny Pfannschmidt <ronny.pfannschmidt@gmail.com>
Status: Draft
Type: Standards Track
Created: 08-Oct-2026
Python-Version: 3.16
Post-History:


Abstract
========

When an ``assert`` statement fails, CPython raises a bare ``AssertionError``.
The values that made the condition false are gone by the time anyone looks
at the exception. Test frameworks get them back by rewriting the abstract
syntax tree of every test module at import time.

This PEP proposes that the compiler do this instead. When an ``assert``
fails, the interpreter attaches a structured *assertion record* to the
``AssertionError``. The record holds:

- the source text of the asserted expression;
- the value of each subexpression that was evaluated, in evaluation order,
  without evaluating anything a second time;
- the explicit message object, if there is one.

The default traceback display renders the record as an explanation in the
style test users already know::

    Traceback (most recent call last):
      File "example.py", line 4, in check
        assert helper() + 1 == len([1, 2]) * 3
    AssertionError
      assert (3 + 1) == (2 * 3)
       +  where 3 = helper()
       +  and   2 = len([1, 2])

A passing assertion stays essentially as cheap as it is today. ``-O``
still removes assertions completely. ``str()`` and ``args`` of the
exception do not change. A process-wide hook lets test frameworks supply
their own explanations, such as pytest's diffs for ``==`` between
containers, without an import hook.


Motivation
==========

Python's ``assert`` is the most common way to state an invariant and, through
pytest, the most common way to write a test assertion. When it fails, though,
the language reports almost nothing::

    >>> def check(items):
    ...     assert len(items) == 3
    ...
    >>> check([1, 2])
    Traceback (most recent call last):
      ...
    AssertionError

People work around this in three ways.

1. **Repeat the operands in a message.** ``assert len(items) == 3,
   f"{len(items)=}"`` evaluates the subexpression a second time and adds
   noise. Nobody does it consistently.

2. **Use assertion methods.** ``unittest``'s ``assertEqual(a, b)`` knows its
   operands because they are arguments. Every kind of check needs its own
   method, and the methods cannot be combined the way expressions can.

3. **Rewrite the assert at import time.** pytest rewrites the ``assert``
   statements of test modules into code that keeps each subexpression in a
   temporary and builds an explanation when the test fails. This works well
   and is the reason ``assert`` became the idiomatic test assertion. It
   costs a lot, though:

   - an import hook, which has to decide which modules to rewrite (test
     files, conftests, explicitly registered plugin modules) and leaves
     every other module with bare asserts;
   - its own bytecode cache, with its own invalidation rules, beside the
     interpreter's;
   - a separate implementation that has to follow every change to the AST
     and to evaluation order, in each tool that does this. pytest has one,
     cot-assert has one, and other runners have their own;
   - asserts in application code, helper libraries not registered for
     rewriting, ``-c`` snippets, the REPL, ``exec()`` and notebooks stay
     bare.

cot-assert [#cot-assert]_ is an independent rewriter that raises a
structured ``AssertionError`` subclass. Writing it showed how hard
"evaluate exactly as Python would, but remember everything" is to get right
in a source-to-source transformation. Its 0.4.0 changelog fixes all of the
following, each a case where the rewritten assert behaved differently from
plain Python:

- ``assert value == f(value := 3)`` passed where plain Python fails, because
  the rewritten code read ``value`` after the call had rebound it;
- names rebound through ``global`` or ``nonlocal`` by a call inside the
  assert compared wrongly for the same reason;
- ``obj.take(f(obj := None))`` raised ``AttributeError``, because the method
  was looked up after its arguments had run;
- ``assert (a or b) and c`` raised ``UnboundLocalError`` when ``a`` was true
  and ``c`` false: an explanation tried to read a temporary for an operand
  that short-circuiting had skipped.

The compiler already knows the evaluation order, the short-circuit
structure and the exact source span of every subexpression (:pep:`657`).
It is the one place that can record the values both correctly and cheaply.


Rationale
=========

The design follows from four requirements, all of which come from
experience with existing rewriters.

**No re-evaluation.** Before assertion rewriting, py.test re-interpreted a
failing assert's expression from source to explain it. *[Needs verification:
the exact pytest versions in which "reinterpretation" was the default and in
which it was removed; believed to be replaced by rewriting in pytest 2.1 and
removed around pytest 3.0.]* Re-interpretation gave wrong explanations for
expressions with side effects and for values that change between calls. Every
value in an assertion record is therefore one the assert actually
computed, and nothing in the expression runs a second time to produce the
record.

**Exact evaluation order and short-circuiting.** Recording must not change
what the assert does. The program has to behave identically whether a
record is kept or not, apart from the record itself and the lifetime of
the objects it refers to. Operands that short-circuiting skipped are not
evaluated and do not appear in the record.

**Pay only on failure.** Asserts guard hot paths in production code as well
as tests. The common case, a passing assert, must not get noticeably
slower, so all formatting and ``repr()`` happen after the failure, and only
when someone looks.

**Structured data first, text second.** Test frameworks, IDEs, CI reporters
and error trackers each present failures differently. A formatted string
would make every one of them parse it, so the record holds the objects
and their source positions, and the text is rendered from them.


Specification
=============

Scope
-----

This PEP changes what happens when the condition of an ``assert`` statement
is false. It does not change the syntax of ``assert``, does not affect
``raise AssertionError(...)`` written by hand, and does not apply to
exceptions raised *while evaluating* the condition (a ``TypeError`` from an
operand, an exception from ``__bool__``). Those propagate unchanged and
carry no record.

What is recorded
----------------

For an ``assert`` statement ``assert test`` or ``assert test, msg``, the
compiler marks each subexpression of ``test`` as *tracked* or not, by its
AST node type:

========================  ===========================================
Node                      Tracked
========================  ===========================================
``Name`` (load)           yes, every scope (local, closure, global,
                          builtin)
``Attribute`` (load)      yes
``Call``                  yes: the result; the callee and each
                          argument are subexpressions in their own
                          right
``Subscript`` (load)      yes; the container and the key are
                          subexpressions. For a slice, the slice
                          bounds are not tracked separately
``BinOp``, ``UnaryOp``    yes
``Compare``               yes, every operand; for a chained
                          comparison, also which link failed
``BoolOp``                yes, the result and each operand that ran
``IfExp``                 the condition and the result; only the
                          branch that ran is evaluated
``NamedExpr``             yes, the assigned value
``Await``                 yes, the awaited result
``Constant``              no (the source text is the value)
``Lambda``, comprehen-    the resulting object only; nothing inside
sions, generator          a nested scope is tracked
expressions
``Starred``, ``**`` args  the iterable or mapping as a whole
f-strings                 the resulting string only
========================  ===========================================

When the assert fails, the record holds one *entry* for each tracked
subexpression that was evaluated on the path to the failure, **in the
order Python evaluated them**. The list is complete and nothing is
duplicated. In particular:

- An operand of ``and``/``or`` that short-circuiting skipped has no entry.
- Only the branch of a conditional expression that ran contributes entries.
- In a chained comparison ``a < b < c`` that fails at ``a < b``, ``c`` was
  not evaluated and has no entry.
- When a name is rebound during the evaluation (by a walrus or through
  ``global``/``nonlocal`` in a call), the entry holds the value the
  expression actually used, which is the value at the moment Python loaded
  the name.
- An entry holds a reference to the value object itself, taken when the
  value was produced. No ``repr()``, ``str()`` or ``__bool__`` runs to make
  the record. ``__bool__`` of the condition runs exactly once, as it does
  today.

Each entry is a ``types.AssertionEntry``, a named-tuple-like object with
these attributes:

``value``
    The object.

``source``
    The source text of the subexpression, such as ``"len([1, 2])"``.

``positions``
    ``(lineno, end_lineno, col_offset, end_col_offset)`` of the
    subexpression, as :pep:`657` defines them for ``co_positions()``. Any
    element may be ``None`` when the position data is unavailable (``-X
    no_debug_ranges``).

``kind``
    The AST node type name, such as ``"Call"``, ``"Name"`` or ``"Compare"``.

``parent``
    The index of the entry for the smallest enclosing tracked expression
    that was evaluated, or ``None`` for the top-level expression. With
    ``kind``, this lets a formatter rebuild the expression tree, as
    pytest-style explanations need, without re-parsing the source.

The assertion record
--------------------

A new type, ``types.AssertionRecord``, holds the record:

``source``
    The source text of the whole condition, as written (not unparsed).
    *[Open issue: where it comes from; see Open Issues.]*

``entries``
    A tuple of ``AssertionEntry`` in evaluation order, as specified above.

``failed_comparison``
    For a chained comparison at the top of the condition, or inside a
    top-level ``and``: the entry index of the failing comparison and the
    0-based index of the failing link within the chain. ``None`` otherwise.

``message``
    The explicit message *object* (the value of ``msg``), or a sentinel
    ``types.NO_MESSAGE`` when the statement had none. The sentinel is needed
    because ``None`` is a legitimate message.

``format(*, maxsize=240) -> str``
    The default explanation text; see `Rendering`_.

``clear() -> None``
    Renders the explanation once and keeps it, then drops ``entries`` and
    ``message``. After this the record keeps no tested object alive, and
    ``format()`` returns the stored text. This mirrors ``finalize()`` in
    cot-assert and ``frame.clear()`` for tracebacks.

The record is immutable apart from ``clear()``. It pickles as its
rendered text: unpickling gives a cleared record. Entries are never sent
across process boundaries as objects.

The exception
-------------

A failing ``assert`` still raises an instance of exactly
``AssertionError``. It is not a subclass (see `Rejected Ideas`_). The
instance gains one attribute:

``AssertionError.__assertion__``
    The ``AssertionRecord``, or ``None``. It is ``None`` for every
    ``AssertionError`` not raised by a failing ``assert`` statement, and
    whenever recording is disabled (see `Disabling the record`_).

The existing behaviour does not change:

- ``args`` is ``(msg,)`` when the statement has a message and ``()``
  otherwise, as today.
- ``str(exc)`` and ``repr(exc)`` are unchanged. ``str()`` of a failed
  ``assert x`` is still ``""``.
- ``__notes__`` is not touched by the interpreter.

The message expression is evaluated after the condition, and only when it
is false, as today. Its value is stored both in ``args[0]`` (unchanged
behaviour) and in ``record.message``.

Interaction with ``-O``
-----------------------

None. Under ``-O`` / ``PYTHONOPTIMIZE`` the compiler still removes
``assert`` statements completely. No code is emitted for the condition, so
nothing is recorded and nothing costs anything. ``__debug__`` keeps its
meaning.

Existing rewriters do not all behave this way. cot-assert, for example,
turns ``assert`` into an ``if``/``raise``, and its rewritten asserts
therefore still run under ``-O`` (verified against cot-assert 0.4.0 while
writing this PEP). Doing the work in the compiler removes this mismatch.

Cost when the assertion passes
------------------------------

When the condition is true, no record object, entry, string or list may be
allocated, and no hook may run. The remaining cost is that tracked values
must still be reachable if the condition turns out false. The reference
strategy is:

- the compiler keeps tracked intermediate values alive in hidden
  fast-local slots (like the hidden slots :pep:`709` uses for inlined
  comprehensions) or on the value stack;
- on success it releases them before the next statement, so the assert
  does not extend any object's lifetime once it has passed;
- on failure a single new instruction builds the record from those slots,
  reading the static parts (sources, positions, kinds, parents per failure
  exit) from a per-code-object table.

A passing assert thus pays a store and a release per tracked
subexpression and nothing else. For comparison, cot-assert's source-level
rewriting, which has to assign and ``del`` real local variables, measured
about 1.34x the time of a plain passing
``assert (helper() + 1) == (len(x) * 2) and x[0] == 1`` on CPython 3.13
(a microbenchmark run while writing this PEP, not a representative
benchmark). A compiler implementation is expected to do clearly better.
This needs to be measured, together with the effect on the specializing
interpreter and the JIT, before the PEP can be accepted.

Static data (entry sources, positions and per-exit layouts) increases the
size of code objects and ``.pyc`` files that contain asserts. The ``.pyc``
magic number changes as it does in every feature release.

Disabling the record
--------------------

``-X assert_record=0`` and the environment variable
``PYTHONASSERTRECORD=0`` disable building records, process-wide. Both are
reflected in ``sys.flags.assert_record``. The check runs on the failure
path only, so it does not change the compiled code, the ``.pyc`` files or
the cost of passing asserts. When disabled, ``__assertion__`` is ``None``,
tracked values are released before the ``AssertionError`` is raised, and
the behaviour is exactly that of Python 3.15. Embedders can set the same
switch in ``PyConfig``.

Rendering
---------

``record.format()`` and the default traceback display produce an explanation
in the format pytest users already read. For the example from the
abstract::

    assert (3 + 1) == (2 * 3)
     +  where 3 = helper()
     +  and   2 = len([1, 2])

With a message, the message comes first, as pytest shows it::

    custom msg
    assert (1 and 0)

The exact layout is **not normative**. The documentation describes it, and
it may change between releases like any other traceback detail. These
rules are normative:

- **Safe repr.** Values are rendered with ``reprlib``-style limits. An
  exception raised by an object's ``__repr__`` does not propagate:
  ``KeyboardInterrupt`` and ``SystemExit`` are re-raised, and any other
  exception is shown in place of the value, as cot-assert and pytest do::

      assert <[ValueError('boom') raised in repr()] Bad object at 0x7f00aebb0ec0> == 1

- **Truncation.** Each value's representation is ellipsized in the middle
  to ``maxsize`` characters (240 by default, pytest's default). Containers
  are abbreviated as ``reprlib`` does: ``[0, 1, 2, 3, 4, 5, ...]``. Newlines
  in a repr are escaped, so one value cannot forge further explanation
  lines.
- **Rendering is lazy.** No ``repr()`` runs until ``format()`` is called or
  the traceback is displayed. A value that is mutated after the failure is
  therefore shown in its later state. *[Open issue: this differs from
  pytest, which formats inside the failure branch; see Open Issues.]*
- **What gets a ``where`` line.** The default renderer gives a line to calls,
  attributes, subscripts and conditional expressions, as pytest does.
  Names inline their repr, except names bound to modules, classes and
  functions, which stay as written. All of these are still present in
  ``entries``. Formatters may present them however they like.

Traceback integration
---------------------

``traceback.TracebackException`` gains an ``assertion`` attribute. It is
the record's rendered text, captured when the ``TracebackException`` is
created, so the text survives after the exception has been cleared. It is
``None`` when there is no record.
``TracebackException.format_exception_only()`` (and so
``traceback.print_exception``, ``sys.excepthook`` and the REPL) emits it
indented after the exception line and before ``__notes__``. Because the
text is rendered then and not when the assert failed, the
``sys.assertionhook`` in effect at display time applies.

``faulthandler`` and the C-level ``PyErr_Display`` fallback do not render
records.

Hooks for test frameworks
-------------------------

pytest's most valued explanations do not come from showing subexpressions.
They come from the ``pytest_assertrepr_compare`` hook, which explains *why*
``left == right`` is false: a diff of two strings, the differing keys of
two dicts, the first differing index of two lists. cot-assert routes the
same step through a replaceable ``Formatter.reprcompare(op, left, right)``.
This PEP provides one standard place for that:

``sys.assertionhook``
    ``None`` by default. If set, it is called as
    ``hook(record, op, left, right)`` when a comparison in the record is
    rendered (``op`` is the operator as text, such as ``"=="`` or
    ``"not in"``; ``left`` and ``right`` are the operand objects). It
    returns either ``None``, to fall back to the default rendering, or a
    list of lines that replaces the one-line ``left op right``. It is
    called at render time only, never when the assert fails, and so never
    on the hot path. An exception raised by the hook is reported through
    ``sys.unraisablehook`` and the default rendering is used.

``sys.getassertionhook()`` / ``sys.setassertionhook(hook)``
    Set and get it. Frameworks are expected to chain to the previous hook
    for comparisons they do not handle.

A test runner then needs no import hook at all. It sets
``sys.assertionhook`` for the session, reads ``exc.__assertion__`` from a
failure, and builds its report from ``record.entries``, or simply calls
``record.format()``. A runner that wants to keep the tested objects only
briefly calls ``record.clear()`` once it has rendered, as cot-assert's
pytest plugin does with ``finalize()``.

Per-type customization (``__assert_explain__``) is discussed under `Open
Issues`_.

Python API summary
------------------

- ``types.AssertionRecord``, ``types.AssertionEntry``, ``types.NO_MESSAGE``
- ``AssertionError.__assertion__``
- ``sys.setassertionhook()``, ``sys.getassertionhook()``
- ``sys.flags.assert_record``, ``-X assert_record``, ``PYTHONASSERTRECORD``
- ``traceback.TracebackException.assertion``

C API: ``PyErr_GetAssertionRecord(PyObject *exc)`` returns a new reference
or ``NULL`` with no exception set.

Other implementations
---------------------

Implementations other than CPython **may** leave ``__assertion__`` as
``None``. Code that reads records must handle ``None`` in any case, since
asserts compiled by older interpreters and hand-raised ``AssertionError``
instances never have one. If an implementation does provide records, they
must follow the evaluation-order and no-re-evaluation rules above. A
partial record that breaks them would mislead the reader.


Backwards Compatibility
=======================

- **The exception type is unchanged.** Exact-type checks
  (``type(e) is AssertionError``), ``except AssertionError`` and
  ``pytest.raises(AssertionError)`` behave as before.
- **str, repr, args and notes are unchanged.** Code that inspects the
  message sees no difference.
- **Traceback output changes.** Anything that compares formatted
  tracebacks byte for byte will see extra lines after ``AssertionError``.
  This includes golden-file tests, log parsers, and possibly ``doctest``:
  examples that expect an ``AssertionError`` may compare more than the last
  line of ``format_exception_only()``. *[Needs verification: how doctest
  extracts the exception line, and whether that follows ``__notes__``-like
  trailing output; the record may have to be excluded from what doctest
  compares, as notes may already be.]*
- **Object lifetime.** Until the exception and its record are released,
  the record keeps the evaluated objects alive. These include intermediate
  results, such as the return value of ``helper()``, that would otherwise
  be freed at once. Tracebacks already keep the failing frame's locals
  alive, so this matters mainly for large intermediates and for code that
  stores caught ``AssertionError`` instances for a long time.
  ``record.clear()`` and ``-X assert_record=0`` address it.
- **Subclasses with an attribute named** ``__assertion__``. Dunder names
  are reserved to the language, so a collision would be user error.
- **Existing rewriters.** pytest's and cot-assert's rewriters replace
  ``assert`` statements with ``if``/``raise`` before compilation, so the
  compiler never sees an ``assert`` there and their behaviour is unchanged.
  On Python 3.16 and later they can stop rewriting and build their reports
  from the record, keeping rewriting only for older versions.
- **Pickling.** An ``AssertionError`` with a record pickles. The record
  pickles as its text (see above), so unpickling needs no access to the
  tested objects' classes.


Security Implications
=====================

- **Values in logs.** Error-reporting services, logging handlers and web
  frameworks' debug pages show tracebacks. With this PEP, a failing
  ``assert token == expected`` in production shows both values. Today only
  locals-capturing reporters do that. Applications that run with asserts
  enabled and handle secrets should review this, and can turn it off with
  ``-X assert_record=0``. This is the main reason the switch exists.
- **Code at display time.** Rendering calls ``__repr__`` of the recorded
  objects, possibly in a logging handler or ``sys.excepthook``, long after
  the failure. Safe repr contains exceptions. It cannot contain a
  ``__repr__`` that blocks, is slow, or is expensive on a huge object.
  ``reprlib`` limits bound the output of built-in containers, but a custom
  ``__repr__`` produces its whole string before it is truncated. The same
  risk exists today with ``traceback`` locals capture
  (``capture_locals=True``) and pytest.
- **Forged output.** Escaping newlines in reprs keeps a value from
  injecting lines that look like part of the explanation or the traceback.
- **No new code execution at failure time.** Building the record runs no
  user code. The hook runs only at render time.


How to Teach This
=================

For most users nothing needs teaching: a failing ``assert`` now says what
the values were. The tutorial section on ``assert`` and the ``AssertionError``
documentation gain a short example of the rendered output.

Points the documentation should make:

- Use plain expressions in asserts. ``assert result == expected`` explains
  itself, and a message is needed only for intent the expression cannot
  show (``assert user.is_active, "deactivated users must not log in"``).
- Asserts are still for invariants and tests, not for input validation:
  ``-O`` still removes them, records and all.
- Values are shown as they are when the traceback is printed, not as they
  were when the assert failed.
- Test-framework authors: read ``exc.__assertion__``, use
  ``sys.setassertionhook()`` for custom comparison explanations, and call
  ``record.clear()`` when the objects are no longer needed.


Reference Implementation
========================

No CPython implementation exists yet.

cot-assert [#cot-assert]_ (package ``cot-assert``, version 0.4.0) prototypes
the semantics at the source level:

- an AST rewriter (``cot_assert._rewrite``) turns each ``assert`` into
  nested ``if`` statements that keep each subexpression in its own
  temporary, preserve Python's evaluation order including the ``global``,
  ``nonlocal`` and walrus cases above, and raise from a separate exit for
  each short-circuit path;
- the runtime entry point ``cot_assert._runtime.fail(site, path, values,
  msg, dynamic=None)`` builds the exception from a prebuilt static
  description of the assert (``AssertSite``: source, a shape tree and the
  slots recorded on each failure path) and the values of the failing path;
- ``AnnotatedAssertion`` (an ``AssertionError`` subclass) keeps the objects
  and renders pytest's explanation format on demand.
  ``finalize("notes" | "message")`` renders once into a :pep:`678` note or
  into ``args`` and drops the objects;
- a pytest plugin replaces pytest's rewriter and routes comparisons to
  ``pytest_assertrepr_compare``. A parity test suite compares its messages
  with pytest's own rewriter on pytest 9 and pytest 4.6, and a fuzz test
  compares generated asserts run plain and rewritten.

The same source runs on CPython 2.7, PyPy 2.7 and CPython 3.9 to 3.14, and
inside RPython, where translated code keeps the values as strings. Its CI
runs the Python 2 targets in containers. This shows that the semantics
need no interpreter support. What source-level rewriting cannot avoid is
the import hook, the separate cache, the cost of real temporaries on
passing asserts, and the correctness bugs listed under Motivation. Those
are the reasons for this PEP.


Rejected Ideas
==============

A new ``AssertionError`` subclass
    cot-assert raises ``AnnotatedAssertion``. For the language, a subclass
    breaks ``type(e) is AssertionError`` checks. It also raises the question
    of what a hand-written ``raise AssertionError`` is, and it adds a public
    exception type whose only job is to carry an attribute. RPython's
    annotator treats every ``AssertionError`` subclass as a built-in
    exception, which is an example of how far tooling special-cases this
    type. An attribute on the existing type avoids all of this.

Putting the explanation in ``args`` or ``str()``
    This changes what existing code observes, breaks ``args == (msg,)``,
    and forces formatting at raise time, so passing asserts would no longer
    be the only cheap path and failures would pay for ``repr()`` even when
    nobody looks. cot-assert offers this only as an opt-in
    (``finalize("message")``) for hosts that cannot show notes.

Adding the explanation as a ``__notes__`` entry at raise time
    :pep:`678` notes are text, and they belong to the user. Adding one at
    raise time formats eagerly and drops the structure. Frameworks can still
    do it themselves from the record, as cot-assert's ``finalize("notes")``
    does.

Re-evaluating the expression on failure
    The approach py.test used before rewriting (see Rationale). It gives
    wrong answers for side effects, iterators, time-dependent values and
    walrus targets.

Formatting reprs when the assert fails
    pytest does this, and it pins the values as they were. But it costs
    ``repr()`` on every failure, including the many failures in production
    code that are caught and handled without being shown, and it runs user
    code (``__repr__``) inside the failing statement. This PEP keeps
    objects and renders lazily; the trade-off is listed as an open issue.

Making records a compile-time option
    A compile-time switch would need its own ``.pyc`` optimization tag, as
    ``-O`` has, and a second set of cache files. Checking a runtime flag on
    the failure path costs nothing when asserts pass.

A new assertion syntax or built-in (``assert_eq``, ``expect``)
    Rust's ``assert_eq!`` and similar forms explain only the two operands of
    one comparison. The value of ``assert`` is that any expression works. A
    second form would split the ecosystem without making ``assert`` itself
    any better.


Open Issues
===========

1. **Lazy versus eager rendering.** Rendering at display time is cheaper and
   runs no user code at failure, but it shows mutated objects in their later
   state. pytest renders eagerly. Options: keep lazy rendering; render
   eagerly when a hook asks for it; or snapshot ``repr()`` of immutable
   built-ins only.
2. **Measured cost of passing asserts.** The claim of "essentially free"
   needs a CPython prototype and pyperformance numbers. That includes the
   specializing interpreter, the JIT, and code-object and ``.pyc`` size for
   assert-heavy test suites.
3. **Source of ``record.source``.** Options: store the source text in the
   code object (larger ``.pyc``); read it lazily through ``linecache`` and
   the positions (unavailable for ``exec()`` of strings and when the
   source has changed); or store ``ast.unparse()`` output, which is what
   cot-assert does, at the cost of not matching what the user wrote.
4. **Which names to track.** cot-assert does not track names that are not
   local to the function (an RPython constraint); pytest shows the repr of
   globals unless they are callable. This PEP tracks every name and leaves
   the presentation to the formatter. Recording globals and builtins
   (``len``) costs a slot each.
5. **Hook shape.** One process-wide ``sys.assertionhook`` for comparisons
   only, or also a per-type protocol such as
   ``__assert_explain__(self, op, other)`` so that libraries (numpy,
   dataclasses, pandas) can explain their own comparisons without depending
   on a test framework? A per-type dunder spreads assertion-specific API
   into data types, and dispatch between left and right operands needs
   rules like the ones for reflected operators.
6. **Default comparison explanations in the standard library.** Should the
   default renderer include diffs for ``str``, ``list`` and ``dict``
   equality, as ``unittest.TestCase.assertEqual`` and pytest do, or leave
   that to hooks?
7. **doctest and golden tracebacks.** See Backwards Compatibility. Is the
   record part of ``format_exception_only()``, or a separate section that
   doctest ignores?
8. **Names.** ``__assertion__``, ``AssertionRecord``, ``assert_record`` and
   ``assertionhook`` are placeholders.
9. **Records from hand-written raises.** Should there be a public way to
   build a record, as cot-assert's ``annotate()`` and ``annotated()``
   allow, so that helper functions such as ``assert_close(a, b)`` can
   produce the same structured output?
10. **Asynchronous and generator frames.** Tracked values held across an
    ``await`` inside an assert must survive suspension. The hidden-slot
    strategy handles this naturally; a value-stack strategy needs checking.


Prior Art
=========

Claims about other languages and tools are from the author's knowledge
and are marked where they still need checking against primary sources.

- **pytest assertion rewriting.** Import-time AST rewriting of test modules
  and plugins, with the ``pytest_assertrepr_compare`` hook for comparison
  explanations. It is the de facto standard this PEP's output format
  follows. *[Needs verification: introduced in pytest 2.1 (2011), replacing
  re-interpretation.]*
- **cot-assert.** Described under Reference Implementation. It provides the
  structured exception, the lazy rendering and the explicit handling of
  evaluation order and short-circuit paths that this PEP adopts.
- **Python's own building blocks.** :pep:`657` (fine-grained error
  locations) provides the positions the entries use; :pep:`678`
  (exception notes) is the model for attaching extra display text to an
  exception; ``traceback.TracebackException(capture_locals=True)`` is
  precedent for showing values in tracebacks. The third-party ``executing``
  library maps a running frame back to the AST node being evaluated, which
  some tools use to explain values without rewriting. *[Needs
  verification: which assertion tools build on it.]*
- **Groovy Power Assert.** Groovy's ``assert`` prints a diagram of every
  subexpression's value under the source line. It originated in the Spock
  framework. *[Needs verification: built into Groovy since 1.7.]*
- **power-assert (JavaScript).** A Babel/compile-time transform that
  instruments ``assert`` calls to produce Groovy-style diagrams. *[Needs
  verification: authorship and current maintenance status.]*
- **Kotlin power-assert.** A compiler plugin that does the same for Kotlin
  function calls such as ``assert``. *[Needs verification: shipped with the
  Kotlin 2.0 compiler.]*
- **Swift.** XCTest's ``XCTAssertEqual`` reports both operands. The newer
  Swift Testing library's ``#expect`` macro captures subexpression values
  at compile time, which is the closest analogue to this PEP in a
  mainstream language. *[Needs verification: details of which
  subexpressions ``#expect`` captures.]*
- **Rust.** ``assert_eq!(a, b)`` and ``assert_ne!`` print both operands
  with their ``Debug`` representation. ``assert!(cond)`` prints only the
  stringified condition unless given a message. There is no subexpression
  capture in the standard library. *[Needs verification: whether third-party
  crates offer power-assert-style macros.]*
- **C and C++.** The C ``assert`` macro prints the stringified expression,
  the file and the line, and no values. C++ test frameworks such as Catch2
  and doctest decompose ``REQUIRE(a == b)`` through operator overloading to
  show both operands. *[Needs verification: exact decomposition limits
  (e.g. no ``&&``/``||``).]*
- **C#.** ``CallerArgumentExpressionAttribute`` (C# 10) passes the source
  text of an argument to the callee. This gives the text half of an
  explanation but no intermediate values. *[Needs verification: whether
  .NET's ``Debug.Assert`` / ``ArgumentNullException.ThrowIfNull`` use it
  by default.]*
- **Elixir.** ExUnit's ``assert`` is a macro that, for a comparison, shows
  the left and right operands and the code. *[Needs verification.]*

What sets this proposal apart from most of these is that it builds the
capture into the compiler of a dynamic language, for its existing
statement, without macros. Groovy is the closest precedent.


References
==========

.. [#cot-assert] cot-assert, "Assertion rewriting that raises a structured
   AnnotatedAssertion", https://github.com/cogs-of-testing/cot.assert


Copyright
=========

This document is placed in the public domain or under the
CC0-1.0-Universal license, whichever is more permissive.

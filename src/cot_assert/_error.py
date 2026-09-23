"""The assertion error raised by rewritten asserts.

Everything in this module that is not marked host-only is in the RPython
subset: fields keep one type per attribute, and host-only paths sit behind
``we_are_translated()``, which the flow space folds to True.
"""

from __future__ import absolute_import, division, print_function

from ._rpy import specialize, we_are_translated
from ._values import value


class AssertSite(object):
    """Static description of one assert statement, prebuilt by the rewriter."""

    def __init__(self, source, path_labels):
        self.source = source
        # One label list per failure path: a path that skipped a short-circuit
        # operand has no value for it. Lists, not tuples: prebuilt tuples of
        # different lengths do not unify in RPython, lists of str do.
        self.path_labels = path_labels


class AnnotatedAssertion(AssertionError):
    """An AssertionError that carries the values its explanation is built from.

    Translated, ``values`` holds str; on the host it holds the objects
    themselves until ``finalize`` renders them and drops them.
    """

    # Unpatched RPython takes every AssertionError subclass for a built-in
    # exception: it skips __init__ and allows no attributes but the ones
    # listed here. Code that has to translate there builds instances with
    # ``annotated()``; see docs/design/rpython.md.
    _attrs_ = ["msg", "site", "path", "values", "labels", "notes", "rendered"]

    def __init__(self, msg=None, site=None, path=0, values=None):
        if not we_are_translated():
            AssertionError.__init__(self)
        self.init_fields(msg, site, path, values)

    def init_fields(self, msg, site, path, values):
        self.msg = msg
        self.site = site
        self.path = path
        if values is None:
            values = []
        self.values = values
        self.labels = []
        self.notes = []
        self.rendered = None

    @specialize.argtype(2)
    def annotate(self, label, obj):
        """Attach a labelled value; the label follows the site's labels."""
        self.labels.append(label)
        self.values.append(value(obj))
        return self

    def all_labels(self):
        if self.site is None:
            return self.labels
        return self.site.path_labels[self.path] + self.labels

    def render_plain(self):
        """The explanation from str values, as translated code can build it."""
        lines = []
        if self.msg is not None:
            lines.append(self.msg)
        if self.site is not None:
            lines.append("assert " + self.site.source)
        labels = self.all_labels()
        i = 0
        while i < len(labels) and i < len(self.values):
            lines.append(" where " + labels[i] + " = " + self.values[i])
            i += 1
        return "\n".join(lines)

    def render(self):
        """Host only: the explanation text."""
        if self.rendered is not None:
            return self.rendered
        from ._render import render

        return render(self)

    def finalize(self, mode="notes"):
        """Host only: render once and drop the tracked values.

        ``mode="notes"`` adds the explanation as a PEP 678 note,
        ``mode="message"`` puts it into ``args`` for hosts that do not show
        notes (pytest 4.6, Python < 3.11 tracebacks).
        """
        if self.values is None:
            return self
        text = self.render()
        self.rendered = text
        self.values = None
        if mode == "notes":
            _add_note(self, text)
        elif mode == "message":
            self.args = (text,)
        else:
            raise ValueError("unknown finalize mode: %r" % (mode,))
        return self

    def __str__(self):
        if we_are_translated():
            return self.render_plain()
        if self.args:
            return str(self.args[0])
        if self.values is None:
            # finalized into notes: the note carries the explanation
            return self.msg if self.msg is not None else ""
        return self.render()


def annotated(msg=None, site=None, path=0, values=None):
    """Build an AnnotatedAssertion; the constructor for RPython code."""
    exc = AnnotatedAssertion()
    exc.init_fields(msg, site, path, values)
    return exc


def _add_note(exc, text):
    add_note = getattr(exc, "add_note", None)
    if add_note is not None:
        add_note(text)
    else:
        notes = getattr(exc, "__notes__", None)
        if notes is None:
            notes = exc.__notes__ = []
        notes.append(text)

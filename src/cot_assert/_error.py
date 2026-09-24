"""The assertion error raised by rewritten asserts.

Everything in this module that is not marked host-only is in the RPython
subset: fields keep one type per attribute, and host-only paths sit behind
``rpy.we_are_translated()``, which the flow space folds to True.
"""

from __future__ import absolute_import, division, print_function

from ._rpy import call_location, rpy
from ._values import value


class AssertSite(object):
    """Static description of one assert statement, prebuilt by the rewriter."""

    def __init__(self, source, path_labels, shape=None, paths=None):
        self.source = source
        # One label list per failure path: a path that skipped a short-circuit
        # operand has no value for it. Lists, not tuples: prebuilt tuples of
        # different lengths do not unify in RPython, lists of str do.
        self.path_labels = path_labels
        # Host only, never read by translated code, so never annotated:
        # the expression tree and per-path records the renderer walks.
        # See _rewrite.AssertRewriter.
        self.shape = shape
        self.paths = paths


class AnnotatedAssertion(AssertionError):
    """An AssertionError that carries the values its explanation is built from.

    Translated, ``values`` holds str; on the host it holds the objects
    themselves until ``finalize`` renders them and drops them.
    """

    # Unpatched RPython takes every AssertionError subclass for a built-in
    # exception: it skips __init__ and allows no attributes but the ones
    # listed here. Code that has to translate there builds instances with
    # ``annotated()``; see docs/design/rpython.md.
    _attrs_ = ["msg", "site", "path", "values", "labels", "rendered"]

    def __init__(self, msg=None, site=None, path=0, values=None):
        if not rpy.we_are_translated():
            AssertionError.__init__(self)
        self.init_fields(msg, site, path, values)

    def init_fields(self, msg, site, path, values):
        self.msg = msg
        if not rpy.we_are_translated():
            # pytest reads msg as text when it catches the exception, before
            # the plugin can finalize it; the object is kept for rendering
            self.msg_obj = msg
            self.msg = _message_text(msg)
        self.site = site
        self.path = path
        if values is None:
            values = []
        self.values = values
        self.labels = []
        self.rendered = None

    @call_location
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
        if mode not in ("notes", "message"):
            raise ValueError("unknown finalize mode: %r" % (mode,))
        if self.values is None:
            return self
        text = self.render()
        # keep only text: nothing that holds on to the tested objects or
        # needs this package's classes to unpickle into a meaningful state
        self.rendered = text
        self.values = None
        self.site = None
        if self.msg is not None:
            self.msg = str(self.msg)
        self.msg_obj = self.msg
        if mode == "notes":
            _add_note(self, text)
        else:
            self.args = (text,)
        return self

    def __reduce__(self):
        # BaseException's reduce passes args to __init__, which reads them
        # as msg/site/...; restore args and state directly instead
        return _unpickle, (type(self), self.args, self.__dict__)

    def __str__(self):
        if rpy.we_are_translated():
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


def _message_text(obj):
    """Host only: the message as AssertionError(obj) would show it."""
    if obj is None or isinstance(obj, _STRING_TYPES):
        return obj
    try:
        return str(obj)
    except Exception:
        return object.__repr__(obj)


try:
    _STRING_TYPES = (basestring,)  # noqa: F821
except NameError:
    _STRING_TYPES = (str,)


def _unpickle(cls, args, state):
    exc = cls.__new__(cls)
    exc.args = args
    exc.__dict__.update(state)
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

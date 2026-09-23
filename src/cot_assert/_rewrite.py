"""Rewrite assert statements to raise AnnotatedAssertion.

The emitted code is kept inside what the RPython flow space accepts and to
plain bytecode: every sub-expression lands in its own temporary (one type
each), short-circuits become nested ``if``s, temporaries are never reset to
None, and the failure branch is a single call per exit that gets the values
evaluated on that path.
"""

from __future__ import absolute_import, division, print_function

import ast
import copy
import sys

from ._unparse import unparse

PY2 = sys.version_info[0] == 2

RUNTIME = "@cot_rt"
DONT_REWRITE = ("COT_DONT_REWRITE", "PYTEST_DONT_REWRITE")

if PY2:
    _NAME_CONSTANTS = ("True", "False", "None")
    _CONST_NODES = (ast.Num, ast.Str)
else:
    _NAME_CONSTANTS = ()
    _CONST_NODES = (ast.Constant,)


def rewrite_source(source, filename="<rewritten>"):
    """Parse, rewrite and compile module source; returns a code object."""
    tree = compile(source, filename, "exec", ast.PyCF_ONLY_AST, True)
    rewrite_asserts(tree)
    # dont_inherit: this module's __future__ flags must not leak into the
    # rewritten one
    return compile(tree, filename, "exec", 0, True)


def rewrite_asserts(module):
    """Rewrite the asserts of an ``ast.Module`` in place."""
    if _is_disabled(module):
        return
    ModuleRewriter().run(module)


def _is_disabled(module):
    doc = _docstring(module)
    return doc is not None and any(marker in doc for marker in DONT_REWRITE)


def _docstring(module):
    if not module.body:
        return None
    first = module.body[0]
    if not isinstance(first, ast.Expr):
        return None
    value = first.value
    if PY2:
        return value.s if isinstance(value, ast.Str) else None
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return None


# -- node construction that works on both AST flavours ----------------------


def _const(value):
    if not PY2:
        return ast.Constant(value)
    if value is None or isinstance(value, bool):
        return ast.Name(repr(value), ast.Load())
    if isinstance(value, (int, float)):
        return ast.Num(value)
    return ast.Str(value)


def _name(id_, store=False):
    return ast.Name(id_, ast.Store() if store else ast.Load())


def _attr(value, attr):
    return ast.Attribute(value, attr, ast.Load())


def _call(func, args):
    if PY2:
        return ast.Call(func, args, [], None, None)
    return ast.Call(func, args, [])


def _raise(exc):
    if PY2:
        return ast.Raise(exc, None, None)
    return ast.Raise(exc, None)


def _not(expr):
    return ast.UnaryOp(ast.Not(), expr)


def _is_constant(node):
    if isinstance(node, _CONST_NODES):
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return _is_constant(node.operand)
    return isinstance(node, ast.Name) and node.id in _NAME_CONSTANTS


# -- scopes -------------------------------------------------------------------


def _function_locals(func):
    """Names local to ``func``: its parameters and everything it binds."""
    names = set()
    args = func.args
    if PY2:
        for arg in args.args:
            names.update(_target_names(arg))
    else:
        for arg in getattr(args, "posonlyargs", []) + args.args + args.kwonlyargs:
            names.add(arg.arg)
    for star in (args.vararg, args.kwarg):
        if star is not None:
            names.add(star if PY2 else star.arg)
    declared_global = set()
    for node in _walk_scope(func.body):
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            names.add(node.id)
        elif isinstance(node, (ast.Global,) + _NONLOCAL):
            declared_global.update(node.names)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, _SCOPES):
            names.add(node.name)
        elif isinstance(node, ast.ExceptHandler) and isinstance(node.name, str):
            names.add(node.name)
    return names - declared_global


_NONLOCAL = () if PY2 else (ast.Nonlocal,)
_SCOPES = (ast.FunctionDef, ast.ClassDef) + (() if PY2 else (ast.AsyncFunctionDef,))


def _target_names(node):
    return [n.id for n in ast.walk(node) if isinstance(n, ast.Name)]


def _walk_scope(body):
    """Walk statements without descending into nested scopes."""
    todo = list(body)
    while todo:
        node = todo.pop()
        yield node
        if isinstance(node, _SCOPES + (ast.Lambda,)):
            continue
        todo.extend(ast.iter_child_nodes(node))


# -- the rewriter ------------------------------------------------------------


class ModuleRewriter(object):
    def __init__(self):
        self.sites = []
        self.counter = 0

    def run(self, module):
        self.rewrite_body(module.body, None)
        if self.sites:
            module.body[_insert_position(module.body) : 0] = self.preamble()
        ast.fix_missing_locations(module)

    def preamble(self):
        stmts = [
            ast.ImportFrom("cot_assert", [ast.alias("_runtime", RUNTIME)], 0),
        ]
        for name, source, path_labels in self.sites:
            labels = ast.List(
                [
                    ast.List([_const(label) for label in path], ast.Load())
                    for path in path_labels
                ],
                ast.Load(),
            )
            site = _call(_attr(_name(RUNTIME), "AssertSite"), [_const(source), labels])
            stmts.append(ast.Assign([_name(name, store=True)], site))
        for stmt in stmts:
            stmt.lineno = 1
            stmt.col_offset = 0
        return stmts

    def fresh(self, prefix):
        self.counter += 1
        return "@%s%d" % (prefix, self.counter)

    def rewrite_body(self, body, local_names):
        """Rewrite asserts in a statement list; ``local_names`` None = module."""
        i = 0
        while i < len(body):
            stmt = body[i]
            if isinstance(stmt, ast.Assert):
                new = AssertRewriter(self, local_names).rewrite(stmt)
                body[i : i + 1] = new
                i += len(new)
                continue
            self.rewrite_children(stmt, local_names)
            i += 1

    def rewrite_children(self, stmt, local_names):
        if isinstance(stmt, ast.FunctionDef) or (
            not PY2 and isinstance(stmt, ast.AsyncFunctionDef)
        ):
            self.rewrite_body(stmt.body, _function_locals(stmt))
            return
        if isinstance(stmt, ast.ClassDef):
            self.rewrite_body(stmt.body, None)
            return
        for field in ("body", "orelse", "finalbody"):
            block = getattr(stmt, field, None)
            if isinstance(block, list):
                self.rewrite_body(block, local_names)
        # except handlers and match cases hold their own statement lists
        for child in getattr(stmt, "handlers", []) + getattr(stmt, "cases", []):
            self.rewrite_body(child.body, local_names)


def _insert_position(body):
    pos = 0
    if _docstring_node(body):
        pos = 1
    while (
        pos < len(body)
        and isinstance(body[pos], ast.ImportFrom)
        and body[pos].module == "__future__"
    ):
        pos += 1
    return pos


def _docstring_node(body):
    if not body or not isinstance(body[0], ast.Expr):
        return False
    value = body[0].value
    if PY2:
        return isinstance(value, ast.Str)
    return isinstance(value, ast.Constant) and isinstance(value.value, str)


class AssertRewriter(object):
    """Rewrites a single assert statement."""

    def __init__(self, module, local_names):
        self.module = module
        self.local_names = local_names
        self.path_labels = []
        self.site_name = module.fresh("cot_site")

    def rewrite(self, stmt):
        self.msg = stmt.msg
        block = []
        self.check(stmt.test, block, [])
        self.module.sites.append((self.site_name, unparse(stmt.test), self.path_labels))
        for new in block:
            ast.copy_location(new, stmt)
        return block

    # -- failure exits --

    def fail(self, evaluated):
        path = len(self.path_labels)
        self.path_labels.append([label for _, label in evaluated])
        values = ast.List(
            [_call(_attr(_name(RUNTIME), "v"), [expr]) for expr, _ in evaluated],
            ast.Load(),
        )
        msg = copy.deepcopy(self.msg) if self.msg is not None else _const(None)
        return _raise(
            _call(
                _attr(_name(RUNTIME), "fail"),
                [_name(self.site_name), _const(path), values, msg],
            )
        )

    def fail_unless(self, test, block, evaluated):
        block.append(ast.If(_not(test), [self.fail(evaluated)], []))

    # -- statement level: fall through when true, raise when false --

    def check(self, expr, block, evaluated):
        if isinstance(expr, ast.BoolOp) and isinstance(expr.op, ast.And):
            for value in expr.values:
                self.check(value, block, evaluated)
        elif isinstance(expr, ast.BoolOp):
            for value in expr.values[:-1]:
                test = self.cond(value, block, evaluated)
                inner = []
                block.append(ast.If(_not(test), inner, []))
                block = inner
            self.check(expr.values[-1], block, evaluated)
        elif isinstance(expr, ast.Compare) and len(expr.ops) > 1:
            left = self.track(expr.left, block, evaluated)
            for op, comparator in zip(expr.ops, expr.comparators):
                right = self.track(comparator, block, evaluated)
                self.fail_unless(ast.Compare(left, [op], [right]), block, evaluated)
                left = right
        else:
            self.fail_unless(self.cond(expr, block, evaluated), block, evaluated)

    def cond(self, expr, block, evaluated):
        """An expression to test, its operands already evaluated into block."""
        if isinstance(expr, ast.Compare) and len(expr.ops) == 1:
            left = self.track(expr.left, block, evaluated)
            right = self.track(expr.comparators[0], block, evaluated)
            return ast.Compare(left, expr.ops, [right])
        return self.track(expr, block, evaluated)

    # -- expression level: evaluate once, remember the value --

    def track(self, expr, block, evaluated):
        """Evaluate ``expr`` into ``block``; return an expression for its value."""
        if _is_constant(expr):
            return expr
        label = unparse(expr)
        if isinstance(expr, ast.Name):
            if self.local_names is None or expr.id in self.local_names:
                evaluated.append((_name(expr.id), label))
            return expr
        new = self.rebuild(expr, block, evaluated)
        temp = self.module.fresh("cot")
        block.append(ast.Assign([_name(temp, store=True)], new))
        evaluated.append((_name(temp), label))
        return _name(temp)

    def rebuild(self, expr, block, evaluated):
        """``expr`` with its sub-expressions replaced by tracked values."""
        if isinstance(expr, ast.Attribute):
            return _attr(self.track(expr.value, block, evaluated), expr.attr)
        if isinstance(expr, ast.BinOp):
            left = self.track(expr.left, block, evaluated)
            right = self.track(expr.right, block, evaluated)
            return ast.BinOp(left, expr.op, right)
        if isinstance(expr, ast.UnaryOp):
            return ast.UnaryOp(expr.op, self.track(expr.operand, block, evaluated))
        if isinstance(expr, ast.Compare) and len(expr.ops) == 1:
            return self.cond(expr, block, evaluated)
        if isinstance(expr, ast.Subscript) and isinstance(expr.ctx, ast.Load):
            value = self.track(expr.value, block, evaluated)
            return ast.Subscript(value, expr.slice, ast.Load())
        if isinstance(expr, ast.Call):
            return self.rebuild_call(expr, block, evaluated)
        return expr

    def rebuild_call(self, call, block, evaluated):
        func = call.func
        if isinstance(func, ast.Attribute):
            # keep the method call shape: a bound method in a temporary is
            # something RPython would have to annotate as a value
            func = _attr(self.track(func.value, block, evaluated), func.attr)
        elif not isinstance(func, ast.Name):
            func = self.track(func, block, evaluated)
        args = []
        for arg in call.args:
            if not PY2 and isinstance(arg, ast.Starred):
                args.append(
                    ast.Starred(self.track(arg.value, block, evaluated), ast.Load())
                )
            else:
                args.append(self.track(arg, block, evaluated))
        keywords = [
            ast.keyword(kw.arg, self.track(kw.value, block, evaluated))
            for kw in call.keywords
        ]
        if PY2:
            starargs = call.starargs
            if starargs is not None:
                starargs = self.track(starargs, block, evaluated)
            kwargs = call.kwargs
            if kwargs is not None:
                kwargs = self.track(kwargs, block, evaluated)
            return ast.Call(func, args, keywords, starargs, kwargs)
        return ast.Call(func, args, keywords)


def load_source(source, name="rewritten"):
    """Rewrite and execute module source; return its namespace."""
    namespace = {"__name__": name}
    exec(rewrite_source(source, "<%s>" % name), namespace)
    return namespace

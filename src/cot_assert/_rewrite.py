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

from ._unparse import binop, cmpop, unaryop, unparse

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


def _literal(value):
    """AST for nested tuples and lists of str, int, bool and None."""
    return ast.parse(repr(value), mode="eval").body


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
    """Names local to ``func`` whose values asserts track.

    Its parameters and everything it binds, except names bound only by
    import: those are modules or globals of other modules, shown by name
    like the globals of this one, and RPython cannot pass a module around.
    """
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
        for name, source, path_labels, shape, paths in self.sites:
            site = _call(
                _attr(_name(RUNTIME), "AssertSite"),
                [
                    _const(source),
                    _literal(path_labels),
                    _literal(shape),
                    _literal(paths),
                ],
            )
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
    """Rewrites a single assert statement.

    Besides the code, it records what the failure explanation needs:

    - slots: every tracked value gets a slot number and a label;
    - paths: per failure exit, the slots evaluated on the way there (in the
      order their values are passed) and the marks that tell which boolean
      operands ran and which comparisons are known to have failed;
    - shape: a tree of tuples mirroring the expression, which the host
      renders the way pytest's rewriter formats its explanations.
    """

    def __init__(self, module, local_names):
        self.module = module
        self.local_names = local_names
        self.site_name = module.fresh("cot_site")
        self.labels = []
        self.paths = []
        self.node_ids = 0
        # (block, temporary) in assignment order
        self.temps = []

    def rewrite(self, stmt):
        self.msg = stmt.msg
        block = []
        shape = self.check(stmt.test, block, _Path())
        self.release_temps()
        path_labels = [[self.labels[slot] for slot in slots] for slots, _ in self.paths]
        self.module.sites.append(
            (self.site_name, unparse(stmt.test), path_labels, shape, self.paths)
        )
        for new in block:
            ast.copy_location(new, stmt)
        return block

    def release_temps(self):
        """Delete temporaries once the assert has passed.

        The end of the block a temporary is assigned in is reached only on
        success, and only when the assignment ran. Deleting rather than
        resetting to None keeps each temporary at one type for RPython, and
        stops it keeping the tested objects alive.
        """
        for block, temp in self.temps:
            block.append(ast.Delete([ast.Name(temp, ast.Del())]))

    def new_id(self):
        self.node_ids += 1
        return self.node_ids

    # -- failure exits --

    def fail(self, path):
        number = len(self.paths)
        self.paths.append((list(path.slots), sorted(path.marks)))
        values = ast.List(
            [_call(_attr(_name(RUNTIME), "v"), [expr]) for expr in path.exprs],
            ast.Load(),
        )
        if self.msg is None:
            msg = _const(None)
        else:
            msg = _call(_attr(_name(RUNTIME), "m"), [copy.deepcopy(self.msg)])
        return _raise(
            _call(
                _attr(_name(RUNTIME), "fail"),
                [_name(self.site_name), _const(number), values, msg],
            )
        )

    def fail_unless(self, test, block, path):
        block.append(ast.If(_not(test), [self.fail(path)], []))

    # -- statement level: fall through when true, raise when false --

    def check(self, expr, block, path):
        """Emit the test for ``expr`` into ``block``; return its shape."""
        if isinstance(expr, ast.BoolOp):
            node = self.new_id()
            is_or = isinstance(expr.op, ast.Or)
            shapes = []
            last = len(expr.values) - 1
            for i, value in enumerate(expr.values):
                path.marks.add(("bool", node, i))
                if is_or and i < last:
                    # a false operand of ``or`` moves on to the next one
                    test, shape = self.cond(value, block, path)
                    inner = []
                    block.append(ast.If(_not(test), inner, []))
                    block = inner
                    shapes.append(shape)
                    self.mark_false(shape, path)
                else:
                    shapes.append(self.check(value, block, path))
            return ("boolop", node, is_or, shapes)
        if isinstance(expr, ast.Compare) and len(expr.ops) > 1:
            node = self.new_id()
            left, left_shape = self.track(expr.left, block, path)
            operands = [left_shape]
            for i, (op, comparator) in enumerate(zip(expr.ops, expr.comparators)):
                right, right_shape = self.track(comparator, block, path)
                operands.append(right_shape)
                test = ast.Compare(left, [op], [right])
                path.marks.add(("cmp", node, i))
                block.append(ast.If(_not(test), [self.fail(path)], []))
                path.marks.discard(("cmp", node, i))
                left = right
            return ("compare", node, [cmpop(op) for op in expr.ops], operands, None)
        test, shape = self.cond(expr, block, path)
        self.mark_false(shape, path)
        self.fail_unless(test, block, path)
        self.unmark_false(shape, path)
        return shape

    def mark_false(self, shape, path):
        if shape[0] == "compare" and shape[4] is None:
            path.marks.add(("cmp", shape[1], 0))

    def unmark_false(self, shape, path):
        if shape[0] == "compare" and shape[4] is None:
            path.marks.discard(("cmp", shape[1], 0))

    def cond(self, expr, block, path):
        """An expression to test, its operands already evaluated into block."""
        if isinstance(expr, ast.Compare) and len(expr.ops) == 1:
            left, left_shape = self.track(expr.left, block, path)
            right, right_shape = self.track(expr.comparators[0], block, path)
            shape = (
                "compare",
                self.new_id(),
                [cmpop(expr.ops[0])],
                [left_shape, right_shape],
                None,
            )
            return ast.Compare(left, expr.ops, [right]), shape
        return self.track(expr, block, path)

    # -- expression level: evaluate once, remember the value --

    def slot(self, expr, label, path):
        slot = len(self.labels)
        self.labels.append(label)
        path.slots.append(slot)
        path.exprs.append(expr)
        return slot

    def track(self, expr, block, path):
        """Evaluate ``expr`` into ``block``; return (value expression, shape)."""
        if _is_constant(expr):
            return expr, ("const", unparse(expr))
        label = unparse(expr)
        if isinstance(expr, ast.Name):
            if self.local_names is None or expr.id in self.local_names:
                return expr, ("name", self.slot(_name(expr.id), label, path), expr.id)
            return expr, ("text", expr.id)
        new, build = self.rebuild(expr, block, path)
        temp = self.module.fresh("cot")
        block.append(ast.Assign([_name(temp, store=True)], new))
        self.temps.append((block, temp))
        slot = self.slot(_name(temp), label, path)
        return _name(temp), build(slot)

    def rebuild(self, expr, block, path):
        """``expr`` over tracked sub-values, and a shape builder taking its slot."""
        if isinstance(expr, ast.Attribute) and isinstance(expr.ctx, ast.Load):
            value, value_shape = self.track(expr.value, block, path)
            attr = expr.attr
            return _attr(value, attr), lambda slot: ("attr", slot, value_shape, attr)
        if isinstance(expr, ast.BinOp):
            left, left_shape = self.track(expr.left, block, path)
            right, right_shape = self.track(expr.right, block, path)
            sym = binop(expr.op)
            return (
                ast.BinOp(left, expr.op, right),
                lambda slot: ("binop", sym, left_shape, right_shape),
            )
        if isinstance(expr, ast.UnaryOp):
            operand, operand_shape = self.track(expr.operand, block, path)
            pattern = unaryop(expr.op) + "%s"
            return (
                ast.UnaryOp(expr.op, operand),
                lambda slot: ("unary", pattern, operand_shape),
            )
        if isinstance(expr, ast.Compare) and len(expr.ops) == 1:
            test, shape = self.cond(expr, block, path)
            return test, lambda slot: shape[:4] + (slot,)
        if isinstance(expr, ast.Call):
            return self.rebuild_call(expr, block, path)
        if isinstance(expr, ast.Subscript) and isinstance(expr.ctx, ast.Load):
            value, _ = self.track(expr.value, block, path)
            return ast.Subscript(value, expr.slice, ast.Load()), _repr_shape
        return expr, _repr_shape

    def rebuild_call(self, call, block, path):
        func = call.func
        if isinstance(func, ast.Attribute):
            # keep the method call shape: a bound method in a temporary is
            # something RPython would have to annotate as a value
            obj, obj_shape = self.track(func.value, block, path)
            func_shape = ("method", obj_shape, func.attr)
            func = _attr(obj, func.attr)
        else:
            func, func_shape = self.track(func, block, path)
        args = []
        arg_shapes = []
        for arg in call.args:
            if not PY2 and isinstance(arg, ast.Starred):
                value, shape = self.track(arg.value, block, path)
                args.append(ast.Starred(value, ast.Load()))
                arg_shapes.append(("*", shape))
            else:
                value, shape = self.track(arg, block, path)
                args.append(value)
                arg_shapes.append(("", shape))
        starargs = kwargs = None
        if PY2 and call.starargs is not None:
            starargs, shape = self.track(call.starargs, block, path)
            arg_shapes.append(("*", shape))
        keywords = []
        for kw in call.keywords:
            value, shape = self.track(kw.value, block, path)
            keywords.append(ast.keyword(kw.arg, value))
            arg_shapes.append(("**" if kw.arg is None else kw.arg + "=", shape))
        if PY2 and call.kwargs is not None:
            kwargs, shape = self.track(call.kwargs, block, path)
            arg_shapes.append(("**", shape))
        if PY2:
            new = ast.Call(func, args, keywords, starargs, kwargs)
        else:
            new = ast.Call(func, args, keywords)
        return new, lambda slot: ("call", slot, func_shape, arg_shapes)


def _repr_shape(slot):
    return ("repr", slot)


class _Path(object):
    """What has been evaluated along the code path being emitted.

    Failure exits only ever come after the code of everything they report,
    and short-circuits only nest, so one growing record per assert is enough.
    """

    def __init__(self):
        self.slots = []
        self.exprs = []
        self.marks = set()


def load_source(source, name="rewritten"):
    """Rewrite and execute module source; return its namespace."""
    namespace = {"__name__": name}
    exec(rewrite_source(source, "<%s>" % name), namespace)
    return namespace

"""A tiny, restricted boolean/arithmetic expression language for report specs
(scripts/report_spec.py) -- never Python's own eval() over attacker-reachable
text. A report spec's `where`/`assert`/`value` strings are evaluated against one
row (a flat dict of already-extracted field values, never a nested object or a
record straight from the book), so the grammar never needs attribute access,
subscripting, or calls at all -- and this module refuses every node outside a
fixed whitelist rather than trying to sandbox a fuller language.

Grammar: comparisons (==, !=, <, <=, >, >=, in, not in), boolean combinators
(and, or, not), arithmetic (+, -, *, /, %, unary -), names (looked up in the
row dict; a name the row doesn't carry evaluates to None, same "absent is
never pass" discipline as the rest of this repo -- a comparison against None
is almost always False, never silently True), literals (str/int/float/bool/
None), and list/tuple display (for `in`/`not in` against a literal set)."""
import ast

_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod)
_ALLOWED_CMPOPS = (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn)


class ExprError(ValueError):
    """An expression used a construct this language refuses, or a row carried
    a value a comparison/arithmetic op can't act on -- raised, never silently
    coerced, so a spec bug fails the run closed instead of mis-scoring a claim."""


def _node_eval(node, row):
    if isinstance(node, ast.Expression):
        return _node_eval(node.body, row)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (str, int, float, bool)) or node.value is None:
            return node.value
        raise ExprError(f"unsupported literal: {node.value!r}")
    if isinstance(node, ast.Name):
        return row.get(node.id)
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_node_eval(e, row) for e in node.elts]
    if isinstance(node, ast.UnaryOp):
        operand = _node_eval(node.operand, row)
        if isinstance(node.op, ast.Not):
            return not operand
        if isinstance(node.op, ast.USub):
            try:
                return -operand
            except TypeError as e:
                raise ExprError(f"unary '-' over a non-numeric value ({operand!r}): {e}") from e
        raise ExprError(f"unsupported unary operator: {type(node.op).__name__}")
    if isinstance(node, ast.BoolOp):
        values = [_node_eval(v, row) for v in node.values]
        return all(values) if isinstance(node.op, ast.And) else any(values)
    if isinstance(node, ast.BinOp):
        if not isinstance(node.op, _ALLOWED_BINOPS):
            raise ExprError(f"unsupported operator: {type(node.op).__name__}")
        left, right = _node_eval(node.left, row), _node_eval(node.right, row)
        if left is None or right is None:
            raise ExprError("arithmetic over a field this row does not carry (None)")
        if isinstance(node.op, (ast.Div, ast.Mod)) and right == 0:
            raise ExprError(f"division by zero ({left!r} {'%' if isinstance(node.op, ast.Mod) else '/'} 0)")
        ops = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
               ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b, ast.Mod: lambda a, b: a % b}
        try:
            return ops[type(node.op)](left, right)
        except TypeError as e:
            # A sealed record's field can be any JSON scalar type -- a row
            # value this arithmetic expects numeric but finds a str/list/dict
            # (claude-security finding, this job, CWE-754) must fail closed
            # as ExprError, not an uncaught TypeError.
            raise ExprError(f"arithmetic over incompatible types ({left!r}, {right!r}): {e}") from e
    if isinstance(node, ast.Compare):
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise ExprError("chained comparisons are not supported")
        op = node.ops[0]
        if not isinstance(op, _ALLOWED_CMPOPS):
            raise ExprError(f"unsupported comparison: {type(op).__name__}")
        left, right = _node_eval(node.left, row), _node_eval(node.comparators[0], row)
        if isinstance(op, ast.Eq):
            return left == right
        if isinstance(op, ast.NotEq):
            return left != right
        if isinstance(op, (ast.In, ast.NotIn)):
            # right is the container (a List/Tuple literal in practice, so
            # usually safe) -- but a row-derived `right` (e.g. a missing field
            # evaluating to None, or a non-container value) makes `in` raise a
            # bare, uncaught TypeError instead of this module's own ExprError,
            # breaking the "a spec bug fails the run closed" promise every
            # caller relies on (desk-review finding, this job).
            try:
                found = left in right
            except TypeError as e:
                raise ExprError(f"'in'/'not in' against a non-container value ({right!r}): {e}") from e
            return found if isinstance(op, ast.In) else not found
        if left is None or right is None:
            raise ExprError("ordering comparison over a field this row does not carry (None)")
        ordering = {ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b,
                    ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b}
        try:
            return ordering[type(op)](left, right)
        except TypeError as e:
            # Same incompatible-types gap as the BinOp branch above, for
            # <, <=, >, >= (claude-security finding, this job, CWE-754).
            raise ExprError(f"ordering comparison over incompatible types ({left!r}, {right!r}): {e}") from e
    raise ExprError(f"unsupported expression node: {type(node).__name__}")


def eval_expr(expr, row):
    """Evaluate `expr` (a string) against `row` (a flat dict). Raises ExprError
    for anything outside the grammar this module documents -- never falls back
    to Python's own eval()/exec(): `expr` is parsed with ast.parse(mode="eval")
    into a syntax tree and walked by _node_eval's own whitelist (Compare/BoolOp/
    UnaryOp/BinOp/Name/Constant/List/Tuple only -- no Call, Attribute, Subscript
    or Lambda node is ever accepted), so no arbitrary code can run even though
    `expr` ultimately comes from a report spec file a caller supplies."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ExprError(f"not a valid expression: {expr!r}: {e}") from e
    return _node_eval(tree, row)

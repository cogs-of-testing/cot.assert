A comparison whose operand is an arithmetic or unary expression
(`x + [9] == y`, `-x == y`) passes the operand's value to pytest's
comparison hook, as pytest's rewriter does. It passed nothing, so such
asserts showed no diff. The value was already captured; only the
explanation dropped it, so translated code is unchanged.

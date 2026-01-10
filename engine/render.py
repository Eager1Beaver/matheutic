from __future__ import annotations

from typing import Dict

from engine.expr import Expression


OP_SYMBOL: Dict[str, str] = {
    '+': '+',
    '-': '-',
    '*': '×',
    '/': '÷',
    }


def render_expression(expr: Expression, with_equals: bool = True) -> str:
    parts = []
    b = expr.brackets

    for i, n in enumerate(expr.numbers):
        if b and i == b.start:
            parts.append('(')

        parts.append(str(n))

        if b and i == b.end:
            parts.append(')')

        if i < len(expr.ops):
            parts.append(OP_SYMBOL.get(expr.ops[i], expr.ops[i]))

    s = ''.join(parts)
    if with_equals:
        s += '='
    return s

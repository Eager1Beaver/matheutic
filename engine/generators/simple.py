from __future__ import annotations

import random
from typing import Any, Dict, List

from ..expr import Expression


def generate_single_op(rng: random.Random, gen_cfg: Dict[str, Any]) -> Expression:
    op = gen_cfg['op']
    n_numbers = int(gen_cfg['n_numbers'])
    operands = gen_cfg['operands']
    lo, hi = int(operands['min']), int(operands['max'])
    rules = gen_cfg.get('rules', {}) or {}

    # Helper to pick a random int in [lo, hi]
    def rint(a: int, b: int) -> int:
        return rng.randint(a, b)

    if op == '/':
        require_int = bool(rules.get('require_integer_division', True))
        if not require_int:
            # TODO: for now only clean integer division is supported.
            require_int = True

        # Choose divisors and a final result, then build the dividend so every step divides evenly.
        divisors: List[int] = []
        for _ in range(n_numbers - 1):
            d = rint(max(lo, 1), hi)
            if d == 0:
                d = 1
            divisors.append(d)

        result = rint(lo, hi)
        dividend = result
        for d in divisors:
            dividend *= d

        # If dividend doesn't fit operand bounds, caller will retry via validation loop.
        numbers = [dividend] + divisors
        ops = ['/'] * (n_numbers - 1)
        return Expression(numbers=numbers, ops=ops)

    if op == '-':
        non_negative_intermediate = bool(rules.get('non_negative_intermediate', rules.get('non_negative', True)))
        if non_negative_intermediate:
            # Pick trailing numbers, then choose the first number large enough to keep running total >= 0.
            tail = [rint(lo, hi) for _ in range(n_numbers - 1)]
            need = sum(tail)
            if need > hi:
                # Still return something deterministically.
                first = hi
            else:
                first = rint(max(need, lo), hi)
            numbers = [first] + tail
        else:
            numbers = [rint(lo, hi) for _ in range(n_numbers)]

        ops = ['-'] * (n_numbers - 1)
        return Expression(numbers=numbers, ops=ops)

    # + or *
    numbers = [rint(lo, hi) for _ in range(n_numbers)]
    ops = [op] * (n_numbers - 1)
    return Expression(numbers=numbers, ops=ops)

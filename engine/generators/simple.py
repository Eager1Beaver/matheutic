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
        # Choose divisors and a final result, then build the dividend so every step divides evenly.
        divisors: List[int] = []
        product = 1
        minimum_divisor = max(lo, 1)
        for index in range(n_numbers - 1):
            # Reserve room for remaining divisors when the dividend must be
            # positive. This avoids almost-certain rejection on long chains.
            upper = hi
            if lo > 0:
                remaining = n_numbers - 2 - index
                upper = min(hi, hi // (product * minimum_divisor**remaining))
            d = rint(minimum_divisor, upper)
            divisors.append(d)
            product *= d

        # The quotient is not an input operand. Bound the dividend, rather than
        # requiring the quotient to lie in the operand range as well.
        q_min = -(-lo // product)
        q_max = hi // product
        dividend = rint(q_min, q_max) * product if q_min <= q_max else product

        # Unusable divisor combinations are rejected by the shared validator.
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

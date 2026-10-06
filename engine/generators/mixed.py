from __future__ import annotations

import random
from typing import Any

from config.schema import operand_range

from ..expr import Brackets, Expression
from .utils import weighted_choice


def _range_for_op(gen_cfg: dict[str, Any], op: str) -> tuple[int, int]:
    return operand_range(gen_cfg, op)


def _subtrahend_range(lo: int, hi: int) -> tuple[int, int]:
    """Bias subtraction to pick smaller right-hand operands."""
    if hi <= lo:
        return lo, hi
    # Use the lower half of the configured range.
    mid = lo + (hi - lo) // 2
    return lo, mid


def generate_mixed(rng: random.Random, gen_cfg: dict[str, Any]) -> Expression:
    n_numbers = int(gen_cfg['n_numbers'])
    ops_allowed: list[str] = list(gen_cfg['operators'])
    weights = gen_cfg.get('operator_weights') or None

    rules = gen_cfg.get('rules', {}) or {}
    non_negative_intermediate = rules.get('non_negative_intermediate', rules.get('non_negative', False))

    ops: list[str] = [weighted_choice(rng, ops_allowed, weights) for _ in range(n_numbers - 1)]

    # Generate numbers sequentially, using the operator to the left as a hint for scale.
    numbers: list[int] = []
    lo0, hi0 = _range_for_op(gen_cfg, ops[0])
    if ops[0] == '/' and lo0 == 0:
        lo0 = 1
    numbers.append(rng.randint(lo0, hi0))

    for op in ops:
        lo, hi = _range_for_op(gen_cfg, op)
        if op == '/':
            lo = max(lo, 1)
        if non_negative_intermediate and op == '-':
            lo, hi = _subtrahend_range(lo, hi)
        numbers.append(rng.randint(lo, hi))

    # TODO: recheck optional single pair of brackets (no nesting)
    br_cfg = gen_cfg.get('brackets') or {}
    brackets = None
    if br_cfg.get('enabled'):
        p = float(br_cfg.get('probability', 0.35))
        if rng.random() < p:
            start = rng.randint(0, n_numbers - 2)
            end = rng.randint(start + 1, n_numbers - 1)
            brackets = Brackets(start=start, end=end)

    return Expression(numbers=numbers, ops=ops, brackets=brackets)

from __future__ import annotations

from dataclasses import dataclass
from typing import list, tuple

from engine.expr import Expression


class EvalError(Exception):
    pass


class NonIntegerDivision(EvalError):
    pass


class DivisionByZero(EvalError):
    pass


@dataclass(frozen=True)
class Step:
    left: int
    op: str
    right: int
    result: int


def _apply_op(a: int, op: str, b: int, require_integer_division: bool) -> int:
    if op == '+':
        return a + b
    if op == '-':
        return a - b
    if op == '*':
        return a * b
    if op == '/':
        if b == 0:
            raise DivisionByZero('division by zero')
        if require_integer_division and (a % b != 0):
            raise NonIntegerDivision(f'{a} / {b} is not an integer')
        return a // b
    raise EvalError(f'unknown operator: {op}')


def _eval_no_brackets(
        numbers: list[int], 
        ops: list[str], 
        require_integer_division: bool,
        ) -> tuple[int, list[Step]]:
    nums = list(numbers)
    o = list(ops)
    steps: list[Step] = []

    # First pass: */ left-to-right
    i = 0
    while i < len(o):
        if o[i] in ('*', '/'):
            a = nums[i]
            b = nums[i + 1]
            r = _apply_op(a, o[i], b, require_integer_division)
            steps.append(Step(a, o[i], b, r))
            nums[i:i+2] = [r]
            o.pop(i)
            continue
        i += 1

    # Second pass: +- left-to-right
    res = nums[0]
    for i, op in enumerate(o):
        b = nums[i + 1]
        r = _apply_op(res, op, b, require_integer_division)
        steps.append(Step(res, op, b, r))
        res = r

    return res, steps


def evaluate_with_steps(expr: Expression, require_integer_division: bool = True) -> tuple[int, list[Step]]:
    if require_integer_division is not True:
        raise EvalError('only integer division is supported')
    # Apply a single level of brackets (no nesting)
    nums = list(expr.numbers)
    ops = list(expr.ops)
    all_steps: list[Step] = []

    if expr.brackets:
        b = expr.brackets
        if not (0 <= b.start < b.end < len(nums)):
            raise EvalError('invalid brackets span')
        sub_nums = nums[b.start:b.end + 1]
        sub_ops = ops[b.start:b.end]
        sub_res, sub_steps = _eval_no_brackets(sub_nums, sub_ops, require_integer_division)
        all_steps.extend(sub_steps)

        # Replace bracketed segment with its result
        nums = nums[:b.start] + [sub_res] + nums[b.end + 1:]
        ops = ops[:b.start] + ops[b.end:]

    res, steps = _eval_no_brackets(nums, ops, require_integer_division)
    all_steps.extend(steps)
    return res, all_steps

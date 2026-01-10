from __future__ import annotations

from typing import Any, Dict, Tuple

from engine.expr import Expression
from engine.eval import evaluate_with_steps, EvalError


def _digits(n: int) -> int:
    n = abs(int(n))
    if n == 0:
        return 1
    d = 0
    while n:
        d += 1
        n //= 10
    return d


def validate_expression(expr: Expression, gen_cfg: Dict[str, Any]) -> Tuple[bool, str, int]:
    rules = gen_cfg.get('rules', {}) or {}
    limits = gen_cfg.get('limits', {}) or {}

    max_operand_digits = limits.get('max_operand_digits')
    if isinstance(max_operand_digits, int):
        for n in expr.numbers:
            if _digits(n) > max_operand_digits:
                return False, 'operand_too_many_digits', 0

    require_int_div = bool(rules.get('require_integer_division', True))

    try:
        final, steps = evaluate_with_steps(expr, require_integer_division=require_int_div)
    except EvalError as e:
        return False, f'eval_error:{e}', 0

    non_negative = bool(rules.get('non_negative', False))
    if non_negative and final < 0:
        return False, 'final_negative', 0

    non_negative_intermediate = bool(rules.get('non_negative_intermediate', non_negative))
    if non_negative_intermediate:
        for st in steps:
            if st.result < 0:
                return False, 'intermediate_negative', 0

    max_inter_digits = limits.get('max_intermediate_digits')
    if isinstance(max_inter_digits, int):
        for st in steps:
            if _digits(st.result) > max_inter_digits:
                return False, 'intermediate_too_many_digits', 0

    max_final_digits = limits.get('max_final_digits')
    if isinstance(max_final_digits, int) and _digits(final) > max_final_digits:
        return False, 'final_too_many_digits', 0

    max_inter_value = limits.get('max_intermediate_value')
    if isinstance(max_inter_value, int):
        for st in steps:
            if abs(st.result) > max_inter_value:
                return False, 'intermediate_too_large', 0

    max_final_value = limits.get('max_final_value')
    if isinstance(max_final_value, int) and abs(final) > max_final_value:
        return False, 'final_too_large', 0

    return True, 'ok', int(final)

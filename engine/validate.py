from __future__ import annotations

from typing import Any

from config.schema import operand_range, validate_generator_config
from engine.eval import EvalError, evaluate_with_steps
from engine.expr import Expression


def _digits(n: int) -> int:
    n = abs(int(n))
    if n == 0:
        return 1
    d = 0
    while n:
        d += 1
        n //= 10
    return d


def validate_expression(expr: Expression, gen_cfg: dict[str, Any]) -> tuple[bool, str, int]:
    validate_generator_config(gen_cfg)
    if len(expr.numbers) != gen_cfg['n_numbers']:
        return False, 'operand_count_mismatch', 0
    allowed = [gen_cfg['op']] if gen_cfg['type'] == 'single_op' else gen_cfg['operators']
    if any(op not in allowed for op in expr.ops):
        return False, 'operator_not_allowed', 0
    if expr.brackets and not (gen_cfg.get('brackets') or {}).get('enabled', False):
        return False, 'brackets_not_allowed', 0
    for i, number in enumerate(expr.numbers):
        lo, hi = operand_range(gen_cfg, expr.ops[max(0, i - 1)])
        if not lo <= number <= hi:
            return False, 'operand_out_of_range', 0
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

from __future__ import annotations

import random
from typing import Any, Dict, List, Tuple, Optional

from engine.expr import Expression
from engine.render import render_expression
from engine.validate import validate_expression
from engine.generators.simple import generate_single_op
from engine.generators.mixed import generate_mixed
from export.pdf import measure_fits


class GenerationError(RuntimeError):
    pass


def _generate_expr(rng: random.Random, gen_cfg: Dict[str, Any]) -> Expression:
    t = gen_cfg['type']
    if t == 'single_op':
        return generate_single_op(rng, gen_cfg)
    if t == 'mixed':
        return generate_mixed(rng, gen_cfg)
    raise GenerationError(f'Unknown generator type: {t}')


def generate_workbook(cfg: Dict[str, Any]) -> Tuple[List[List[str]], Optional[List[List[str]]]]:
    seed = cfg.get('seed')
    rng = random.Random(seed) if seed is not None else random.Random()

    layout = cfg['layout']
    rows = int(layout['rows_per_column'])
    max_attempts = int(layout['max_attempts_per_cell'])

    n_cols = len(cfg['columns'])
    columns_out: List[List[str]] = []
    answers_out: List[List[str]] = []

    answers_cfg = cfg.get('answers', {}) or {}
    want_answers = bool(answers_cfg.get('enabled', False))

    for col_idx, col_spec in enumerate(cfg['columns']):
        gen_name = col_spec['generator']
        gen_cfg = cfg['generators'][gen_name]

        col_texts: List[str] = []
        col_answers: List[str] = []

        for r in range(rows):
            ok = False
            last_reason = 'unknown'

            for attempt in range(max_attempts):
                expr = _generate_expr(rng, gen_cfg)
                valid, reason, ans = validate_expression(expr, gen_cfg)
                last_reason = reason
                if not valid:
                    continue

                text = render_expression(expr, with_equals=True)
                if not measure_fits(text, cfg, n_cols):
                    last_reason = 'does_not_fit_column_width'
                    continue

                col_texts.append(text)
                if want_answers:
                    col_answers.append(str(ans))
                ok = True
                break

            if not ok:
                raise GenerationError(
                    f"Failed to generate row {r+1} in column {col_idx+1} (generator '{gen_name}'). "
                    f"Last failure reason: {last_reason}. "
                    f"Try loosening constraints or increasing layout.max_attempts_per_cell."
                    )

        columns_out.append(col_texts)
        if want_answers:
            answers_out.append(col_answers)

    return columns_out, (answers_out if want_answers else None)

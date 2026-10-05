"""Worksheet presentation and file orchestration around the arithmetic engine."""
from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

from config.schema import normalize_config
from engine.generation import Exercise, GenerationError, generate_exercise
from engine.render import render_expression
from export.pdf import export_worksheet_pdf, measure_fits


class LayoutError(ValueError):
    pass


def generate_workbook(cfg: dict) -> tuple[list[list[str]], list[list[str]] | None]:
    cfg = normalize_config(cfg)
    rng = random.Random(cfg['seed'])
    layout = cfg['layout']
    n_cols = len(cfg['columns'])
    want_answers = cfg['answers']['enabled']
    columns: list[list[str]] = []
    answers: list[list[str]] = []

    def fits(exercise: Exercise) -> bool:
        text = render_expression(exercise.expression)
        if want_answers:
            text += f'  {exercise.answer}'
        if measure_fits(text, cfg, n_cols):
            return True
        if layout['overflow_policy'] == 'error':
            raise LayoutError('Exercise does not fit column width; adjust columns, margins, or font size')
        return False

    for col_idx, spec in enumerate(cfg['columns']):
        texts: list[str] = []
        results: list[str] = []
        for row in range(layout['rows_per_column']):
            try:
                exercise = generate_exercise(
                    rng, cfg['generators'][spec['generator']],
                    max_attempts=layout['max_attempts_per_cell'], accept=fits,
                )
            except GenerationError as error:
                raise GenerationError(
                    f"Failed at row {row + 1}, column {col_idx + 1}, generator '{spec['generator']}': {error}",
                    reason=error.reason, attempts=error.attempts,
                ) from error
            texts.append(render_expression(exercise.expression))
            results.append(str(exercise.answer))
        columns.append(texts)
        answers.append(results)
    return columns, answers if want_answers else None


@dataclass(frozen=True)
class WorksheetFiles:
    worksheet: Path
    answers: Path | None


def write_workbook(
    cfg: dict, out_path: str | Path, *, answers_out: str | Path | None = None,
) -> WorksheetFiles:
    """Reusable file workflow shared by the CLI and future front ends."""
    cfg = normalize_config(cfg)
    output = Path(out_path)
    answer_path = None
    if cfg['answers']['enabled']:
        answer_path = Path(answers_out) if answers_out is not None else output.with_name(
            output.stem + cfg['answers']['suffix'] + output.suffix
        )
        if answer_path.resolve() == output.resolve():
            raise ValueError('Worksheet and answer key must have different output paths')
    columns, answers = generate_workbook(cfg)
    output.parent.mkdir(parents=True, exist_ok=True)
    title = cfg['meta'].get('title')
    export_worksheet_pdf(cfg, columns, output, title=title)
    if answer_path is not None:
        answer_path.parent.mkdir(parents=True, exist_ok=True)
        export_worksheet_pdf(
            cfg, columns, answer_path, answers=answers,
            title=f'{title} - Answers' if title else 'Answers',
        )
    return WorksheetFiles(output, answer_path)

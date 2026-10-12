"""Select bounded, verified practice calculations using the arithmetic engine."""
from __future__ import annotations

import random
from dataclasses import dataclass
from math import isqrt

from ai.errors import GeneratedProblemInvalid, GenerationExhausted
from config.schema import ConfigError
from core.constraints import ProblemConstraints
from core.expression import ExpressionAnalysis
from core.problem_validator import (
    ProblemValidationError,
    ValidationIssue,
    validate_expression,
)
from engine.generation import GenerationError, generate_exercise
from engine.render import render_expression


@dataclass(frozen=True)
class CalculationPlan:
    expression: str
    analysis: ExpressionAnalysis


def select_calculation(
        constraints: ProblemConstraints, 
        *, 
        rng: random.Random | None = None,
        max_attempts: int = 2000,
        ) -> CalculationPlan:
    """Sample an engine exercise and enforce the coach's independent result ranges."""
    rng = rng or random.Random()
    counts = list(range(constraints.min_operations, constraints.max_operations + 1))
    rng.shuffle(counts)
    allowed = list(constraints.allowed_operations)
    accepted = None
    sample_min = constraints.min_operand
    if constraints.max_operand > 0 and constraints.max_final_value != 0 and set(allowed) <= {"*", "/"}:
        sample_min = max(1, sample_min)

    def accept(exercise):
        nonlocal accepted
        expression = render_expression(exercise.expression, with_equals=False).replace("×", "*").replace("÷", "/")
        try:
            accepted = CalculationPlan(expression, validate_expression(expression, constraints))
        except ProblemValidationError:
            return False
        return True

    for count in counts:
        config = {
            "type": "single_op" if len(allowed) == 1 else "mixed", 
            "n_numbers": count + 1,
            "operands": {"min": sample_min, "max": constraints.max_operand},
            "rules": {"non_negative": True, "non_negative_intermediate": True, "require_integer_division": True},
            }
        if len(allowed) == 1:
            config["op"] = allowed[0]
        else:
            config["operators"] = allowed
            cap = constraints.max_intermediate_value or constraints.max_final_value or constraints.max_operand
            ceiling = max(constraints.min_operand, min(constraints.max_operand, max(12, isqrt(cap))))
            config["operands_by_operator"] = {op: {"min": constraints.min_operand, "max": ceiling} for op in allowed if op in ("*", "/")}
        try:
            generate_exercise(rng, config, max_attempts=max(1, max_attempts // len(counts)), accept=accept)
        except ConfigError:
            continue
        except GenerationError:
            continue
        return accepted
    raise GenerationExhausted([GeneratedProblemInvalid([ValidationIssue(
        "calculation_generation_exhausted", 
        "No calculation satisfying all preferences was found within the generation budget."
        )]
        )])

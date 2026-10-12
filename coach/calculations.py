"""Select bounded, verified practice calculations using the arithmetic engine."""
from __future__ import annotations

import random
from dataclasses import dataclass
from math import isqrt

from ai.errors import GeneratedProblemInvalid, GenerationExhausted
from config.schema import MAX_ATTEMPTS, ConfigError
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
        preferred_operations: int | None = None,
        ) -> CalculationPlan:
    """Sample an engine exercise and enforce the coach's independent result ranges."""
    if type(max_attempts) is not int or not 1 <= max_attempts <= MAX_ATTEMPTS:
        raise ValueError(f"max_attempts must be an integer from 1 to {MAX_ATTEMPTS}")
    rng = rng or random.Random()
    counts = list(range(constraints.min_operations, constraints.max_operations + 1))
    rng.shuffle(counts)
    if preferred_operations is not None:
        counts.sort(key=lambda count: abs(count - preferred_operations))
    allowed = list(constraints.allowed_operations)
    accepted = None

    prefer_useful = True

    def accept(exercise):
        nonlocal accepted
        expression = render_expression(exercise.expression, with_equals=False).replace("×", "*").replace("÷", "/")
        try:
            accepted = CalculationPlan(expression, validate_expression(expression, constraints))
        except ProblemValidationError:
            return False
        if prefer_useful and any(  # noqa: SIM103
                (step.operation == "*" and (step.left in (0, 1) or step.right in (0, 1)))
                or (step.operation in ("/", "-") and step.right == (1 if step.operation == "/" else 0))
                or (step.operation == "+" and (step.left == 0 or step.right == 0))
                for step in accepted.analysis.steps):
            return False
        return True

    jobs = [(useful, count) for useful in (True, False) for count in counts]
    remaining = max_attempts
    for index, (prefer_useful, count) in enumerate(jobs):
        if remaining == 0:
            break
        sample_min = constraints.min_operand
        if prefer_useful and constraints.max_operand > 0 and constraints.max_final_value != 0 and set(allowed) <= {"*", "/"}:
            sample_min = max(1, sample_min)
        if allowed == ["/"] and sample_min > 0 and sample_min ** count > constraints.max_operand:
            continue
        config = {
            "type": "single_op" if len(allowed) == 1 else "mixed", 
            "n_numbers": count + 1,
            "operands": {"min": sample_min, "max": constraints.max_operand},
            "rules": {"non_negative": True, "non_negative_intermediate": True, "require_integer_division": True},
            }
        if len(allowed) == 1:
            config["op"] = allowed[0]
            if prefer_useful and allowed[0] == "*":
                cap = constraints.max_final_value
                if cap is not None:
                    ceiling = max(sample_min, min(constraints.max_operand, int(cap ** (1 / (count + 1)))))
                    config["operands"]["max"] = ceiling
        else:
            config["operators"] = allowed
            cap = constraints.max_intermediate_value or constraints.max_final_value or constraints.max_operand
            ceiling = max(constraints.min_operand, min(constraints.max_operand, max(12, isqrt(cap))))
            config["operands_by_operator"] = {op: {"min": constraints.min_operand, "max": ceiling} for op in allowed if op in ("*", "/")}
        try:
            budget = max(1, remaining // (len(jobs) - index))
            remaining -= budget
            generate_exercise(rng, config, max_attempts=budget, accept=accept)
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

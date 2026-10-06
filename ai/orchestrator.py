"""Bounded generation and deterministic validation of arithmetic problems."""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.constraints import ProblemConstraints
from core.expression import ExpressionAnalysis
from core.problem_validator import (
    ProblemValidationError,
    ValidationIssue,
    validate_problem,
    )

from .errors import (
    GeneratedProblemInvalid,
    GenerationExhausted,
    ProblemConstraintViolation,
    UnsupportedProblemRequest,
    )
from .provider import AIProvider

if TYPE_CHECKING:
    from .schemas import MathProblem

logger = logging.getLogger(__name__)

# These checks concern the caller's policy rather than expression/metadata consistency.
_CONSTRAINT_CODES = frozenset({
    "operation_not_allowed", "required_operation_missing", "operation_count_mismatch",
    "operand_out_of_range", "non_integer_division", "final_negative",
    "intermediate_negative", "intermediate_too_large", "final_too_large",
    })


@dataclass(frozen=True)
class ValidatedProblem:
    problem: MathProblem
    analysis: ExpressionAnalysis
    attempts: int


@dataclass(frozen=True)
class GenerationRejection:
    attempt: int
    error: GeneratedProblemInvalid
    problem: MathProblem | None = None


def classify_validation_error(error: ProblemValidationError) -> GeneratedProblemInvalid:
    """Distinguish policy violations from invalid arithmetic or metadata."""
    error_type = (ProblemConstraintViolation
                  if all(issue.code in _CONSTRAINT_CODES for issue in error.issues)
                  else GeneratedProblemInvalid)
    return error_type(error.issues)


class ProblemGenerator:
    """Obtain validated candidates with a bounded regeneration budget."""

    def __init__(
            self, 
            provider: AIProvider, 
            constraints: ProblemConstraints | None = None,
            *, max_attempts: int = 3
            ) -> None:
        if constraints is not None and not isinstance(constraints, ProblemConstraints):
            raise TypeError("constraints must be ProblemConstraints")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 5:
            raise ValueError("max_attempts must be an integer from 1 to 5")
        self.provider = provider
        self.constraints = ProblemConstraints() if constraints is None else constraints
        self.max_attempts = max_attempts

    async def generate(
            self, 
            request: str, 
            language: str = "en", 
            *,
            on_rejection: Callable[[GenerationRejection], None] | None = None,
            ) -> ValidatedProblem:
        """Regenerate invalid candidates; propagate unsupported requests and service failures."""
        if not isinstance(request, str) or not request.strip():
            raise UnsupportedProblemRequest("An arithmetic request is required.", reason="empty_request")
        if language != "en":
            raise UnsupportedProblemRequest("Problem content must use English.", reason="unsupported_language")
        if self.constraints.max_operand == 0 and (
            "/" in self.constraints.required_operations
            or self.constraints.allowed_operations == ("/",)
            ):
            raise UnsupportedProblemRequest(
                "Division cannot use only zero operands.", reason="impossible_constraints"
                )

        failures: list[GeneratedProblemInvalid] = []
        for attempt in range(1, self.max_attempts + 1):
            problem = None
            try:
                problem = await self.provider.generate_problem(request=request, language=language)
                if not isinstance(problem.statement, str) or not problem.statement.strip():
                    raise GeneratedProblemInvalid([
                        ValidationIssue("empty_statement", "The problem statement must not be empty.")
                        ])
                if len(problem.statement) > 4000:
                    raise GeneratedProblemInvalid([
                        ValidationIssue("statement_too_long", "The problem statement exceeds 4000 characters.")
                        ])
                analysis = validate_problem(problem, self.constraints)
            except ProblemValidationError as error:
                failure = classify_validation_error(error)
            except GeneratedProblemInvalid as error:
                failure = error
            else:
                return ValidatedProblem(problem, analysis, attempt)

            failures.append(failure)
            logger.warning(
                "Rejected arithmetic candidate: attempt=%s/%s category=%s issues=%s",
                attempt, self.max_attempts, type(failure).__name__,
                "; ".join(f"{issue.code}: {issue.message}" for issue in failure.issues),
                )
            if on_rejection is not None:
                on_rejection(GenerationRejection(attempt, failure, problem))

        raise GenerationExhausted(failures) from failures[-1]

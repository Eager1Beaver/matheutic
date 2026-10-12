"""Bounded generation and deterministic validation of arithmetic problems."""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from core.constraints import ProblemConstraints
from core.expression import ExpressionAnalysis, expression_structure
from core.problem_validator import (
    ProblemValidationError,
    ValidationIssue,
    validate_expression,
    validate_problem,
)

from .errors import (
    GeneratedProblemInvalid,
    GenerationExhausted,
    ProblemConstraintViolation,
    UnsupportedProblemRequest,
)
from .policy import natural_number_policy
from .provider import AIProvider

if TYPE_CHECKING:
    from .schemas import MathProblem, ProblemContent, StoryReview

logger = logging.getLogger(__name__)

# These checks concern the caller's policy rather than expression/metadata consistency.
_CONSTRAINT_CODES = frozenset({
    "operation_not_allowed", "required_operation_missing", "operation_count_mismatch",
    "operand_out_of_range", "non_integer_division", "final_negative",
    "intermediate_negative", "intermediate_too_large", "final_too_large",
    "difficulty_mismatch",
    "required_expression_mismatch", "fixed_operands_mismatch",
    })


@dataclass(frozen=True)
class ValidatedProblem:
    problem: MathProblem
    analysis: ExpressionAnalysis
    attempts: int
    constraints: ProblemConstraints | None = None
    request_diagnostics: dict | None = None
    story_review: StoryReview | None = None


@dataclass(frozen=True)
class GenerationRejection:
    attempt: int
    error: GeneratedProblemInvalid
    problem: ProblemContent | MathProblem | None = None
    constraints: ProblemConstraints | None = None
    request_diagnostics: dict | None = None
    story_review: StoryReview | None = None


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
            *, 
            max_attempts: int = 3, 
            difficulty: int | None = None,
            dev_mode: bool = False,
            review_story: bool = False,
            request_diagnostics: dict | None = None,
            ) -> None:
        if constraints is not None and not isinstance(constraints, ProblemConstraints):
            raise TypeError("constraints must be ProblemConstraints")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 5:
            raise ValueError("max_attempts must be an integer from 1 to 5")
        if difficulty is not None and (type(difficulty) is not int or not 1 <= difficulty <= 5):
            raise ValueError("difficulty must be an integer from 1 to 5")
        if type(dev_mode) is not bool:
            raise ValueError("dev_mode must be a boolean")
        if type(review_story) is not bool:
            raise ValueError("review_story must be a boolean")
        self.provider = provider
        self.constraints = natural_number_policy(constraints)
        self.max_attempts = max_attempts
        self.difficulty = difficulty
        self.dev_mode = dev_mode
        self.review_story = review_story
        self.request_diagnostics = request_diagnostics

    async def _review_story(self, problem, language: str):
        """Read and validate the provider's independent story review output."""
        from pydantic import ValidationError

        from .schemas import StoryReview

        review = await self.provider.review_story(
            request=json.dumps({"statement": problem.statement}, ensure_ascii=False, separators=(",", ":")),
            language=language, dev_mode=self.dev_mode,
        )
        try:
            return StoryReview.model_validate(review.model_dump() if isinstance(review, StoryReview) else review)
        except ValidationError as error:
            raise GeneratedProblemInvalid([
                ValidationIssue("invalid_story_review", "The provider returned an invalid story review.")
            ]) from error

    def _validate_story(self, review, expression: str) -> None:
        issues = []
        for rejected, code, message in (
            (not review.has_story, "not_story", "The statement is a bare calculation rather than a story."),
            (not review.has_question, "missing_question", "The story does not ask for a quantity."),
            (review.ambiguous, "ambiguous_story", "The story has no unambiguous arithmetic interpretation."),
            (not review.consistent_quantities, "inconsistent_story", "The story contains inconsistent quantities."),
        ):
            if rejected:
                issues.append(ValidationIssue(code, message))
        if review.expression is None:
            issues.append(ValidationIssue("missing_story_expression", "The story's calculation could not be reconstructed."))
        else:
            try:
                validate_expression(review.expression, replace(self.constraints, required_expression=None))
                matches = (
                    expression_structure(review.expression, commutative=True)
                    == expression_structure(expression, commutative=True)
                    )
            except ProblemValidationError:
                matches = False
            if not matches:
                issues.append(ValidationIssue("story_expression_mismatch", "The independently reconstructed calculation disagrees with the candidate."))
        if issues:
            raise GeneratedProblemInvalid(issues)

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
        # TODO: will be more languages; maybe pass a list of supported ones
        # and an error will be raised specifying supported languages
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
            review = None
            try:
                problem = await self.provider.generate_problem(
                    request=request, language=language, dev_mode=self.dev_mode,
                    )
                if not isinstance(problem.statement, str) or not problem.statement.strip():
                    raise GeneratedProblemInvalid([
                        ValidationIssue("empty_statement", "The problem statement must not be empty.")
                        ])
                if len(problem.statement) > 4000:
                    raise GeneratedProblemInvalid([
                        ValidationIssue("statement_too_long", "The problem statement exceeds 4000 characters.")
                        ])
                has_answer = hasattr(problem, "answer")
                has_operations = hasattr(problem, "operations")
                if has_answer != has_operations:
                    raise GeneratedProblemInvalid([
                        ValidationIssue("incomplete_metadata", "Answer and operations must be supplied together.")
                        ])
                analysis = (validate_problem(problem, self.constraints) if has_answer
                            else validate_expression(problem.expression, self.constraints))
                if self.difficulty is not None and problem.difficulty != self.difficulty:
                    raise ProblemConstraintViolation([
                        ValidationIssue("difficulty_mismatch", "Declared difficulty does not match the requested level.")
                        ])
                if self.review_story:
                    review = await self._review_story(problem, language)
                    self._validate_story(review, problem.expression)
            except ProblemValidationError as error:
                failure = classify_validation_error(error)
            except GeneratedProblemInvalid as error:
                failure = error
            else:
                if not has_answer:
                    from .schemas import MathProblem

                    problem = MathProblem(
                        statement=problem.statement, expression=problem.expression,
                        difficulty=problem.difficulty, language=language,
                        answer=analysis.value.numerator,
                        operations=list(dict.fromkeys(analysis.operations)),
                        )
                return ValidatedProblem(problem, analysis, attempt, self.constraints, self.request_diagnostics, review)

            failures.append(failure)
            logger.warning(
                "Rejected arithmetic candidate: attempt=%s/%s category=%s issues=%s",
                attempt, self.max_attempts, type(failure).__name__,
                "; ".join(f"{issue.code}: {issue.message}" for issue in failure.issues),
                )
            if on_rejection is not None:
                on_rejection(GenerationRejection(attempt, failure, problem, self.constraints, self.request_diagnostics, review))

        raise GenerationExhausted(failures) from failures[-1]

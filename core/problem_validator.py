"""Independent checks of candidate arithmetic and application constraints."""
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from core.constraints import SUPPORTED_OPERATIONS, ProblemConstraints
from core.expression import (
    MAX_ARITHMETIC_BITS,
    ExpressionAnalysis,
    ExpressionError,
    analyze_expression,
    )


class ProblemCandidate(Protocol):
    """Read-only mathematical fields consumed by problem validation."""

    @property
    def expression(self) -> str: ...

    @property
    def answer(self) -> int: ...

    @property
    def operations(self) -> Sequence[str]: ...


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str


class ProblemValidationError(ValueError):
    def __init__(self, issues: Sequence[ValidationIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(issue.message for issue in self.issues))


def validate_problem(
    problem: ProblemCandidate, constraints: ProblemConstraints | None = None,
    ) -> ExpressionAnalysis:
    """Verify arithmetic, declared metadata, and caller-supplied constraints."""
    constraints = ProblemConstraints() if constraints is None else constraints
    if not isinstance(constraints, ProblemConstraints):
        raise TypeError("constraints must be ProblemConstraints")
    try:
        analysis = analyze_expression(problem.expression)
    except ExpressionError as error:
        raise ProblemValidationError([ValidationIssue(error.code, str(error))]) from error

    issues: list[ValidationIssue] = []

    def reject(code: str, message: str) -> None:
        issues.append(ValidationIssue(code, message))

    answer = problem.answer
    if type(answer) is not int or abs(answer).bit_length() > MAX_ARITHMETIC_BITS:
        reject("invalid_answer", "Declared answer must be an integer within the arithmetic limit.")
    if analysis.value.denominator != 1:
        reject("non_integer_result", "Expression does not produce an integer result.")
    elif type(answer) is int and analysis.value != answer:
        reject("wrong_answer", "Declared answer does not match the calculated result.")

    declared = problem.operations
    valid_metadata = (isinstance(declared, Sequence) and not isinstance(declared, (str, bytes))
                      and bool(declared) and len(declared) <= len(SUPPORTED_OPERATIONS)
                      and all(type(op) is str and op in SUPPORTED_OPERATIONS for op in declared))
    if not valid_metadata:
        reject("invalid_operations", "Declared operations must be an array of supported operators.")
    elif len(set(declared)) != len(declared):
        reject("duplicate_operations", "Declared operations must list each used operator once.")
    elif set(declared) != set(analysis.operations):
        reject("operation_mismatch", "Declared operations do not match the expression.")

    actual = set(analysis.operations)
    if not actual <= set(constraints.allowed_operations):
        reject("operation_not_allowed", "Expression uses an operation forbidden by the request constraints.")
    if not set(constraints.required_operations) <= actual:
        reject("required_operation_missing", "Expression omits a required operation.")
    if not constraints.min_operations <= len(analysis.operations) <= constraints.max_operations:
        reject("operation_count_mismatch", "Expression does not meet the required operation count.")
    if any(not constraints.min_operand <= operand <= constraints.max_operand for operand in analysis.operands):
        reject("operand_out_of_range", "An operand is outside the allowed range.")
    if constraints.require_integer_division and any(
        step.operation == "/" and step.result.denominator != 1 for step in analysis.steps
        ):
        reject("non_integer_division", "Every division must produce an exact integer result.")
    if constraints.non_negative and analysis.value < 0:
        reject("final_negative", "The final result must be non-negative.")
    if constraints.non_negative_intermediate and any(value < 0 for value in analysis.intermediate_values):
        reject("intermediate_negative", "Intermediate results must be non-negative.")
    if constraints.max_intermediate_value is not None and any(
        abs(value) > constraints.max_intermediate_value for value in analysis.intermediate_values
        ):
        reject("intermediate_too_large", "An intermediate result exceeds the allowed magnitude.")
    if constraints.max_final_value is not None and abs(analysis.value) > constraints.max_final_value:
        reject("final_too_large", "The final result exceeds the allowed magnitude.")
    if issues:
        raise ProblemValidationError(issues)
    return analysis

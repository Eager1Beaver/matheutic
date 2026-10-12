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


def _analyze(expression: str) -> ExpressionAnalysis:
    try:
        return analyze_expression(expression)
    except ExpressionError as error:
        raise ProblemValidationError([ValidationIssue(error.code, str(error))]) from error


def _arithmetic_issues(
        analysis: ExpressionAnalysis, 
        constraints: ProblemConstraints,
        ) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    def reject(code: str, message: str) -> None:
        issues.append(ValidationIssue(code, message))

    if analysis.value.denominator != 1:
        reject("non_integer_result", "Expression does not produce an integer result.")
    actual = set(analysis.operations)
    if not actual <= set(constraints.allowed_operations):
        reject("operation_not_allowed", f"Forbidden operators: {sorted(actual - set(constraints.allowed_operations))}.")
    if not set(constraints.required_operations) <= actual:
        reject("required_operation_missing", f"Missing required operators: {sorted(set(constraints.required_operations) - actual)}.")
    if not constraints.min_operations <= len(analysis.operations) <= constraints.max_operations:
        reject("operation_count_mismatch", f"Expression has {len(analysis.operations)} operations; "
               f"expected {constraints.min_operations}..{constraints.max_operations}.")
    if any(not constraints.min_operand <= operand <= constraints.max_operand for operand in analysis.operands):
        outside = sorted(
            {operand for operand in analysis.operands
             if not constraints.min_operand <= operand <= constraints.max_operand}
             )
        reject("operand_out_of_range",
               f"Operands {outside} are outside the inclusive range "
               f"{constraints.min_operand}..{constraints.max_operand}.")
    if constraints.require_integer_division and any(
        step.operation == "/" and step.result.denominator != 1 for step in analysis.steps
        ):
        reject("non_integer_division", "Every division must produce an exact integer result.")
    if constraints.non_negative and analysis.value < 0:
        reject("final_negative", "The final result must be non-negative.")
    if constraints.non_negative_intermediate and any(value < 0 for value in analysis.intermediate_values):
        reject("intermediate_negative", "Intermediate results must be non-negative.")
    intermediate = (analysis.intermediate_values if constraints.intermediate_includes_final
                    else analysis.intermediate_values[:-1])
    if constraints.min_intermediate_value is not None and any(
        value < constraints.min_intermediate_value for value in intermediate
        ):
        reject("intermediate_too_small", f"Intermediate results must be at least {constraints.min_intermediate_value}.")
    if constraints.min_final_value is not None and analysis.value < constraints.min_final_value:
        reject("final_too_small", f"The final answer must be at least {constraints.min_final_value}.")
    if constraints.max_intermediate_value is not None and any(
        abs(value) > constraints.max_intermediate_value for value in intermediate
        ):
        outside = [str(value) for value in intermediate
                   if abs(value) > constraints.max_intermediate_value]
        reject("intermediate_too_large",
               f"Calculated values {outside} exceed the intermediate limit {constraints.max_intermediate_value}.")
    if constraints.max_final_value is not None and abs(analysis.value) > constraints.max_final_value:
        reject("final_too_large",
               f"Final value {analysis.value} exceeds the final limit {constraints.max_final_value}.")
    return issues


def validate_expression(
        expression: str, 
        constraints: ProblemConstraints | None = None,
        ) -> ExpressionAnalysis:
    """Verify an expression's arithmetic and constraints and return its exact analysis."""
    constraints = ProblemConstraints() if constraints is None else constraints
    if not isinstance(constraints, ProblemConstraints):
        raise TypeError("constraints must be ProblemConstraints")
    analysis = _analyze(expression)
    issues = _arithmetic_issues(analysis, constraints)
    if issues:
        raise ProblemValidationError(issues)
    return analysis



def validate_problem(
        problem: ProblemCandidate, 
        constraints: ProblemConstraints | None = None,
        ) -> ExpressionAnalysis:
    """Verify arithmetic, declared metadata, and caller-supplied constraints."""
    constraints = ProblemConstraints() if constraints is None else constraints
    if not isinstance(constraints, ProblemConstraints):
        raise TypeError("constraints must be ProblemConstraints")
    analysis = _analyze(problem.expression)
    issues: list[ValidationIssue] = []
    answer = problem.answer
    if type(answer) is not int or abs(answer).bit_length() > MAX_ARITHMETIC_BITS:
        issues.append(ValidationIssue(
            "invalid_answer", "Declared answer must be an integer within the arithmetic limit."
            ))
    if analysis.value.denominator == 1 and type(answer) is int and analysis.value != answer:
        issues.append(ValidationIssue("wrong_answer", "Declared answer does not match the calculated result."))

    declared = problem.operations
    valid_metadata = (isinstance(declared, Sequence) and not isinstance(declared, (str, bytes))
                      and bool(declared) and len(declared) <= len(SUPPORTED_OPERATIONS)
                      and all(type(op) is str and op in SUPPORTED_OPERATIONS for op in declared))
    if not valid_metadata:
        issues.append(ValidationIssue(
            "invalid_operations", "Declared operations must be an array of supported operators."
            ))
    elif len(set(declared)) != len(declared):
        issues.append(ValidationIssue(
            "duplicate_operations", "Declared operations must list each used operator once."
            ))
    elif set(declared) != set(analysis.operations):
        issues.append(ValidationIssue("operation_mismatch", "Declared operations do not match the expression."))

    issues.extend(_arithmetic_issues(analysis, constraints))
    if issues:
        raise ProblemValidationError(issues)
    return analysis

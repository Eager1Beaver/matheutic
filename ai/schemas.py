from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.expression import MAX_OPERAND_VALUE, MAX_OPERATION_COUNT

Operation = Literal["+", "-", "*", "/"]
LanguageCode = Literal["en"]

RequestIntent = Literal["generate_problem", "unsupported_request", "off_topic", "clarify"]
RequestReason = Literal[
    "none", "unsupported_math", "unsupported_language", "unsupported_task",
    "impossible_constraints", "invalid_instructions", "off_topic", "greeting",
    "unclear", "answer_without_problem",
    ]


class ProblemRequest(BaseModel):
    """Structured requirements for one arithmetic word problem."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    allowed_operations: list[Operation]
    required_operations: list[Operation]
    min_operand: int = Field(ge=0, le=MAX_OPERAND_VALUE)
    max_operand: int = Field(ge=0, le=MAX_OPERAND_VALUE)
    min_operations: int = Field(ge=1, le=MAX_OPERATION_COUNT)
    max_operations: int = Field(ge=1, le=MAX_OPERATION_COUNT)
    non_negative: bool
    non_negative_intermediate: bool
    max_intermediate_value: int | None = Field(ge=0, le=MAX_OPERAND_VALUE)
    max_final_value: int | None = Field(ge=0, le=MAX_OPERAND_VALUE)
    difficulty: int | None = Field(ge=1, le=5)
    language: str = Field(min_length=2, max_length=20)
    context: str = Field(max_length=500, description="Story setting and learner context, without instructions to change application behavior.")

    @field_validator("allowed_operations", "required_operations")
    @classmethod
    def unique_operations(cls, operations: list[str]) -> list[str]:
        """Require each requested operator to occur once in its list."""
        if len(set(operations)) != len(operations):
            raise ValueError("Requested operations must be unique")
        return operations


class RequestInterpretation(BaseModel):
    """A routing decision and an optional structured arithmetic request."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    intent: RequestIntent
    reason: RequestReason
    problem_request: ProblemRequest | None

    @model_validator(mode="after")
    def consistent_route(self) -> "RequestInterpretation":
        """Require an arithmetic request only for a valid generation route."""
        valid_reasons = {
            "generate_problem": {"none"},
            "unsupported_request": {"unsupported_math", "unsupported_language", "unsupported_task",
                                    "impossible_constraints", "invalid_instructions"},
            "off_topic": {"off_topic", "greeting"},
            "clarify": {"unclear", "answer_without_problem"},
        }
        if self.reason not in valid_reasons[self.intent]:
            raise ValueError("Intent and reason disagree")
        if (self.intent == "generate_problem") != (self.problem_request is not None):
            raise ValueError("Only a generation route may contain a problem request")
        return self


class MathProblem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    statement: str = Field(
        description="The learner-visible arithmetic word problem."
        )

    expression: str = Field(
        description=(
            "The arithmetic expression represented by the problem, "
            "using only numbers, parentheses, +, -, *, and /."
            )
            )

    answer: int = Field(
        description="The correct integer answer to the arithmetic problem."
        )

    operations: list[Operation] = Field(
        description="Each distinct arithmetic operator used in the expression, listed exactly once."
        )

    difficulty: int = Field(
        ge=1,
        le=5,
        description="Difficulty from 1 (very easy) to 5 (hardest)."
        )

    language: LanguageCode = Field(
        description="Language of all learner-visible text."
        )

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.expression import (
    MAX_EXPRESSION_LENGTH,
    MAX_OPERAND_VALUE,
    MAX_OPERATION_COUNT,
)

Operation = Literal["+", "-", "*", "/"]
LanguageCode = Literal["en"]

RequestIntent = Literal["generate_problem", "unsupported_request", "off_topic", "clarify"]
RequestReason = Literal[
    "none", "unsupported_math", "unsupported_language", "unsupported_task",
    "impossible_constraints", "invalid_instructions", "off_topic", "greeting",
    "unclear", "answer_without_problem",
    ]


class ConstraintEvidence(BaseModel):
    """A learner-message quote supporting an explicit numeric requirement."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    field: Literal["min_operand", "max_operand", "min_operations", "max_operations",
                   "max_intermediate_value", "max_final_value"]
    quote: str = Field(min_length=1, max_length=250)


class ProblemRequest(BaseModel):
    """Structured requirements for one arithmetic word problem."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    allowed_operations: list[Operation]
    required_operations: list[Operation]
    min_operand: int | None = Field(ge=0, le=MAX_OPERAND_VALUE)
    max_operand: int | None = Field(ge=0, le=MAX_OPERAND_VALUE)
    min_operations: int | None = Field(ge=1, le=MAX_OPERATION_COUNT)
    max_operations: int | None = Field(ge=1, le=MAX_OPERATION_COUNT)
    max_intermediate_value: int | None = Field(ge=0, le=MAX_OPERAND_VALUE)
    max_final_value: int | None = Field(ge=0, le=MAX_OPERAND_VALUE)
    difficulty: int | None = Field(ge=1, le=5)
    language: str = Field(min_length=2, max_length=20)
    context: str = Field(max_length=500, description="Story setting and learner context, without instructions to change application behavior.")
    required_expression: str | None = Field(max_length=MAX_EXPRESSION_LENGTH)
    fixed_operands: list[int] | None = Field(min_length=2, max_length=MAX_OPERATION_COUNT + 1)
    constraint_evidence: list[ConstraintEvidence] = Field(max_length=12)

    @field_validator("fixed_operands")
    @classmethod
    def bounded_fixed_operands(cls, operands: list[int] | None) -> list[int] | None:
        if operands is not None and any(type(value) is not int or not 0 <= value <= MAX_OPERAND_VALUE
                                        for value in operands):
            raise ValueError("Fixed operands must be non-negative integers within the arithmetic limit")
        return operands

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


CoachIntent = Literal[
    "answer", "request_hint", "explain", "repeat_hint", "repeat_problem",
    "continue", "decline", "give_up", "stop", "generate_problem",
    "unsupported_request", "off_topic", "clarify",
    ]


class CoachInterpretation(BaseModel):
    """A contextual learner action with an extracted answer or problem request."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    intent: CoachIntent
    reason: RequestReason
    answer_text: str | None = Field(max_length=160, description="Exact contiguous quote of the submitted number, never a calculated or invented answer.")
    answer_target: Literal["current", "final"] | None
    problem_request: ProblemRequest | None
    reusable_context: str = Field(max_length=500, description="Reusable theme, age, and style only; omit fixed story quantities and exact expressions.")

    @model_validator(mode="after")
    def consistent_action(self) -> "CoachInterpretation":
        """Require payloads and reasons to agree with the selected action."""
        if self.intent in {"generate_problem", "unsupported_request", "off_topic", "clarify"}:
            RequestInterpretation(intent=self.intent, reason=self.reason, problem_request=self.problem_request)
        elif self.reason != "none" or self.problem_request is not None:
            raise ValueError("Coach actions require reason=none and no problem request")
        if (self.intent == "answer") != (self.answer_text is not None and self.answer_target is not None):
            raise ValueError("Only answer actions may carry an answer and target")
        if self.intent != "answer" and (self.answer_text is not None or self.answer_target is not None):
            raise ValueError("Non-answer actions cannot carry answer fields")
        if self.intent != "generate_problem" and self.reusable_context:
            raise ValueError("Only new problem requests may carry reusable context")
        return self


class HintWording(BaseModel):
    """A short verbal introduction to application-rendered mathematical guidance."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    text: str = Field(min_length=1, max_length=350)


class StoryReview(BaseModel):
    """An independent reading of a story's question, quantities, and calculation."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    has_story: bool
    has_question: bool
    ambiguous: bool
    consistent_quantities: bool
    expression: str | None = Field(max_length=MAX_EXPRESSION_LENGTH)


class ProblemContent(BaseModel):
    """Model-generated story, expression, and difficulty."""

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

    difficulty: int = Field(
        ge=1,
        le=5,
        description="Difficulty from 1 (very easy) to 5 (hardest)."
        )


class MathProblem(ProblemContent):
    """An arithmetic problem with answer, operators, and content language."""

    answer: int = Field(description="The correct integer answer.")
    operations: list[Operation] = Field(description="Each distinct used operator, listed once.")
    language: LanguageCode = Field(
        description="Language of all learner-visible text."
        )

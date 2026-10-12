from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from config.difficulty import MAX_PROGRESSIVE_DIFFICULTY
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
    "unclear", "answer_without_problem", "unsupported_custom_problem", "unsupported_difficulty",
    ]


class ProblemRequest(BaseModel):
    """Explicit learner preferences and relative changes for arithmetic practice."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    allowed_operations: list[Operation] | None = Field(description="Explicitly requested operators: addition=['+'], subtraction=['-'], multiplication=['*'], division=['/']. Null only when none is specified.")
    required_operations: list[Operation] | None = Field(description="Operators that must appear. A single requested operator or an AND list is required; an OR list is only allowed. Null or [] when unspecified.")
    min_operand: int | None = Field(ge=0, le=MAX_OPERAND_VALUE)
    max_operand: int | None = Field(ge=0, le=MAX_OPERAND_VALUE)
    min_operations: int | None = Field(ge=1, le=MAX_OPERATION_COUNT, description="Explicit minimum operation count. Exactly N operations/steps sets BOTH count fields to N; two-operation means 2.")
    max_operations: int | None = Field(ge=1, le=MAX_OPERATION_COUNT, description="Explicit maximum operation count. Exactly N operations/steps sets BOTH count fields to N; two-step means 2.")
    min_intermediate_value: int | None = Field(ge=0, le=MAX_OPERAND_VALUE)
    max_intermediate_value: int | None = Field(ge=0, le=MAX_OPERAND_VALUE)
    min_final_value: int | None = Field(ge=0, le=MAX_OPERAND_VALUE)
    max_final_value: int | None = Field(ge=0, le=MAX_OPERAND_VALUE)
    difficulty: int | None = Field(ge=1, le=5)
    difficulty_change: Literal[-1, 0, 1]
    inherit_previous: bool = Field(description="True only for a relative request when previous_request exists, such as another or this time. False for a fresh request.")
    unresolved: bool
    clear_limits: list[Literal["min_intermediate_value", "max_intermediate_value", "min_final_value", "max_final_value"]] | None
    language: str = Field(min_length=2, max_length=20)
    theme: str | None = Field(max_length=100, description="A short setting explicitly requested by the learner, otherwise null.")
    style: str | None = Field(max_length=100, description="An explicitly requested learner level or wording style, otherwise null.")

    @field_validator("allowed_operations", "required_operations")
    @classmethod
    def unique_operations(cls, operations):
        """Require each requested operator to occur once in its list."""
        if operations is not None and len(set(operations)) != len(operations):
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
            "unsupported_request": {
                "unsupported_math", "unsupported_language", "unsupported_task",
                "impossible_constraints", "invalid_instructions", "unsupported_custom_problem", 
                "unsupported_difficulty",
                },
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
        return self


class HintWording(BaseModel):
    """A short verbal introduction to application-rendered mathematical guidance."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    text: str = Field(min_length=1, max_length=350)


class StoryWording(BaseModel):
    """Learner-visible wording for an application-selected arithmetic calculation."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    statement: str = Field(min_length=1, max_length=4000)


class StoryReview(BaseModel):
    """An independent reading of a story's question, quantities, and calculation."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    has_story: bool
    has_question: bool
    ambiguous: bool
    consistent_quantities: bool
    disclosed_results: list[str] = Field(
        max_length=8, 
        description="Exact quotes disclosing computed intermediate or final answers; [] when none. " \
        "Original input quantities are not disclosures."
        )
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
        description="Standard difficulty from 1 (very easy) to 5 (hard)."
        )


class MathProblem(ProblemContent):
    """An arithmetic problem with answer, operators, and content language."""

    difficulty: int = Field(
        ge=1, 
        le=MAX_PROGRESSIVE_DIFFICULTY,
        description="Practice level; above five requires contextual harder progression.",
        )
    answer: int = Field(description="The correct integer answer.")
    operations: list[Operation] = Field(description="Each distinct used operator, listed once.")
    language: LanguageCode = Field(
        description="Language of all learner-visible text."
        )

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Operation = Literal["+", "-", "*", "/"]
LanguageCode = Literal["en"]


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

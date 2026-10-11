"""Verified hint targets, bounded hint progression, and verbal rendering."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from ai.errors import AIProviderError, HintGenerationInvalid
from ai.provider import AIProvider
from core.problem_validator import ValidationIssue

from .answers import NUMBER_WORDS
from .session import ProblemRun

logger = logging.getLogger(__name__)

_DIRECTIONS = {
    "+": "Combine the quantities by adding them.",
    "-": "Find what remains or the difference by subtracting.",
    "*": "Combine equal groups by multiplying.",
    "/": "Share the quantity into equal groups by dividing.",
    }

_STRATEGIES = {
    "+": "Count on from the starting quantity, or add in smaller chunks.",
    "-": "Count backwards, or subtract in smaller chunks.",
    "*": "Think of repeated addition of equal groups.",
    "/": "Think about which multiplication would undo this division.",
    }


@dataclass(frozen=True)
class HintPlan:
    level: int
    step_index: int | None
    direction: str
    task: str


def plan_hint(run: ProblemRun, *, repeat: bool = False) -> HintPlan | None:
    """Select a final-answer hint or the next unresolved calculation step."""
    steps = run.validated.analysis.steps
    multi = len(steps) > 1
    index = (run.step_index if run.step_index is not None else 0) if multi else None
    level = run.hint_level if repeat and run.hint_level else run.hint_level + 1
    if level > (4 if multi else 3):
        return None
    step = steps[index if index is not None else 0]
    direction = _DIRECTIONS[step.operation]
    if level >= 3:
        direction = _STRATEGIES[step.operation]
    calculation = f"{step.left} {step.operation} {step.right}"
    if multi:
        task = f"Step {index + 1} of {len(steps)}: work out {calculation}. What is this step's result?"
    elif level == 1:
        task = "Try the problem again. What is the final answer?"
    else:
        task = f"Work out {calculation}. What is the final answer?"
    if level == 3:
        partial = (step.left + 1 if step.operation == "+" and step.right > 1 else
                   step.left - 1 if step.operation == "-" and step.right > 1 else None)
        if partial is not None and partial != step.result:
            symbol = step.operation
            task = f"Start with {step.left} {symbol} 1 = {partial}, then handle the remaining {step.right - 1}.\n{task}"
        elif step.operation == "*" and step.right > 2 and step.left > 0:
            partial = step.left * 2
            if partial != step.result:
                task = f"Start with {step.left} * 2 = {partial}, then account for the remaining {step.right - 2} groups.\n{task}"
    if level == 4:
        task = f"Focus on just this calculation before moving on.\n{task}"
    return HintPlan(level, index, direction, task)


def validate_wording(text: str) -> str:
    """Reject quantities, calculations, and answer disclosures in verbal introductions."""
    if not isinstance(text, str) or not text.strip() or len(text) > 350:
        raise HintGenerationInvalid([ValidationIssue("invalid_hint_text", "Hint wording is empty or too long.")])
    words = set(re.findall(r"[a-z]+", text.lower()))
    if (words & (NUMBER_WORDS | {"dozen", "half", "twice", "double", "triple"})
            or re.search(r"[\d+*/=<>^\n\r?×÷−–]", text)
            or "-" in text or re.search(r"\b(?:answer|result)\s+is\b|\bequals\b", text, re.I)):
        raise HintGenerationInvalid([ValidationIssue("hint_contains_math", "Verbal hint wording contains mathematical content.")])
    return text.strip()


async def render_hint(
        provider: AIProvider, 
        run: ProblemRun, 
        plan: HintPlan, 
        *, 
        language: str, 
        dev_mode: bool, 
        question: str = "",
        ) -> str:
    """Phrase a hint with a deterministic fallback and append verified guidance."""
    from pydantic import ValidationError

    from ai.schemas import HintWording

    payload = {
        "statement": run.validated.problem.statement, "direction": plan.direction,
        "hint_level": plan.level, "mode": "explanation" if question else "hint",
        "learner_question": question[:600], "recent_turns": list(run.recent_turns),
        }
    try:
        wording = await provider.phrase_hint(
            request=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            language=language, dev_mode=dev_mode,
            )
        try:
            wording = HintWording.model_validate(wording.model_dump() if isinstance(wording, HintWording) else wording)
        except ValidationError as error:
            raise HintGenerationInvalid([ValidationIssue("invalid_hint_schema", "The provider returned invalid hint wording.")]) from error
        introduction = validate_wording(wording.text)
    except AIProviderError as error:
        logger.warning("Hint wording fallback: category=%s", type(error).__name__)
        introduction = plan.direction
    return f"{introduction}\n\n{plan.task}"


def solution_text(run: ProblemRun) -> str:
    """Render the independently computed solution and final answer."""
    steps = "\n".join(f"{step.left} {step.operation} {step.right} = {step.result}" for step in run.validated.analysis.steps)
    return f"Here's the solution:\n{steps}\nFinal answer: {run.validated.analysis.value}"

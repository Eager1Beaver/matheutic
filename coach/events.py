"""Learning events produced by a coach turn before reply delivery."""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from ai.intent import RequestDecision
from ai.orchestrator import ValidatedProblem


@dataclass(frozen=True)
class ProblemStarted:
    problem_id: str
    validated: ValidatedProblem
    request: RequestDecision
    source: str
    selection_metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ProblemEnded:
    problem_id: str
    status: str
    reason: str


@dataclass(frozen=True)
class AttemptMade:
    problem_id: str
    value: Fraction
    expected: Fraction
    step_index: int | None
    final: bool
    correct: bool
    hints_used: int
    operation: str | None


@dataclass(frozen=True)
class HintShown:
    problem_id: str
    kind: str
    level: int
    step_index: int | None
    consumes_hint: bool


LearningEvent = ProblemStarted | ProblemEnded | AttemptMade | HintShown

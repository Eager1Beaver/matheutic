"""In-memory coach sessions and per-problem tutoring records."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from fractions import Fraction
from uuid import uuid4

from ai.intent import RequestDecision
from ai.orchestrator import ValidatedProblem


class CoachState(StrEnum):
    IDLE = "IDLE"
    AWAITING_ANSWER = "AWAITING_ANSWER"
    OFFERING_HINT = "OFFERING_HINT"
    PROBLEM_COMPLETE = "PROBLEM_COMPLETE"


@dataclass(frozen=True)
class AnswerAttempt:
    value: Fraction
    step_index: int | None
    correct: bool


@dataclass
class ProblemRun:
    validated: ValidatedProblem
    problem_id: str = field(default_factory=lambda: uuid4().hex)
    attempts: int = 0
    final_attempts: int = 0
    recent_attempts: deque[AnswerAttempt] = field(default_factory=lambda: deque(maxlen=20))
    hints_used: int = 0
    hint_level: int = 0
    step_index: int | None = None
    steps_solved: int = 0
    last_hint: str | None = None
    outcome: str | None = None
    recent_turns: deque[dict[str, str]] = field(default_factory=lambda: deque(maxlen=8))

    @property
    def expected_answer(self) -> Fraction:
        """Return the final answer or the current verified step result."""
        if self.step_index is None:
            return self.validated.analysis.value
        return self.validated.analysis.steps[self.step_index].result

    def remember(self, role: str, text: str) -> None:
        """Keep bounded excerpts of the latest exchanges about this problem."""
        self.recent_turns.append({"role": role, "text": text[:500]})


@dataclass
class CoachSession:
    state: CoachState = CoachState.IDLE
    run: ProblemRun | None = None
    repeat_request: RequestDecision | None = None
    difficulty: int | None = None
    language: str = "en"

    @property
    def active(self) -> bool:
        """Whether an unfinished problem is awaiting learner input."""
        return self.run is not None and self.state in {
            CoachState.AWAITING_ANSWER, CoachState.OFFERING_HINT,
            } and self.run.outcome is None


class InMemorySessionStore:
    """Store independent sessions by chat and learner identity."""

    def __init__(self) -> None:
        self._sessions: dict[tuple[int, int], CoachSession] = {}

    def get(self, key: tuple[int, int]) -> CoachSession:
        """Return a saved session or a fresh, unsaved idle session."""
        return self._sessions.get(key, CoachSession())

    def save(self, key: tuple[int, int], session: CoachSession) -> None:
        """Replace the session after its reply has been delivered."""
        self._sessions[key] = session

    def reset(self, key: tuple[int, int]) -> None:
        """Remove this conversation's problem and retained request."""
        self._sessions.pop(key, None)

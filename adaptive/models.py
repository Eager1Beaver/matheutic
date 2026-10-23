"""Typed observations and effects for adaptive arithmetic practice."""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from ai.intent import RequestDecision
from core.constraints import ProblemConstraints
from core.expression import ExpressionAnalysis


@dataclass(frozen=True)
class AttemptFact:
    value: Fraction
    step_index: int | None
    final: bool
    correct: bool
    hints_before: int


@dataclass(frozen=True)
class ProblemObservation:
    id: str
    difficulty: int
    constraints: ProblemConstraints
    analysis: ExpressionAnalysis
    status: str
    end_reason: str | None
    attempts: tuple[AttemptFact, ...] = ()
    hints_used: int = 0
    metadata: dict = field(default_factory=dict)
    finished_at: str = ""

    @property
    def assessable(self) -> bool:
        return bool(self.attempts) and self.status != "active" and self.end_reason not in {"stopped", "session_reset"}

    @property
    def clean(self) -> bool:
        return self.status == "solved" and len(self.attempts) == 1 and self.hints_used == 0 and self.attempts[0].correct

    @property
    def difficult(self) -> bool:
        from config.adaptive import REPEATED_WRONG_ATTEMPTS
        return self.status == "revealed" or sum(not a.correct for a in self.attempts) >= REPEATED_WRONG_ATTEMPTS


@dataclass(frozen=True)
class EvidenceSnapshot:
    attempted_count: int = 0
    assessable_count: int = 0
    problems: tuple[ProblemObservation, ...] = ()
    current: ProblemObservation | None = None


@dataclass(frozen=True)
class OperatorSignal:
    operation: str
    upper_bound: int
    problem_ids: tuple[str, ...]
    difficult_count: int
    recent_difficult: bool


@dataclass(frozen=True)
class EvidenceSummary:
    attempted_count: int
    assessable_count: int
    experience: str
    recent_pattern: str
    recent_ids: tuple[str, ...]
    clean_count: int
    independent_count: int
    assisted_count: int
    difficult_count: int
    revealed_count: int
    unfinished_count: int
    broader_count: int
    operator_signals: tuple[OperatorSignal, ...]


@dataclass(frozen=True)
class AdaptiveState:
    plan: RequestDecision | None = None
    variant: str = "standard"
    proposal_id: str | None = None
    revision: int = 0
    activation_count: int = 0
    last_offer_count: int | None = None
    feedback: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AdaptiveDecision:
    kind: str = "hold"
    action: str = ""
    reason: str = ""
    operation: str | None = None
    upper_bound: int | None = None


@dataclass(frozen=True)
class PracticeProposal:
    id: str
    action: str
    reason: str
    baseline: RequestDecision
    target: RequestDecision
    evidence: dict
    policy_version: str


@dataclass(frozen=True)
class ProposalOffered:
    proposal: PracticeProposal
    assessable_count: int
    trigger_problem_id: str | None


@dataclass(frozen=True)
class ProposalResponded:
    proposal_id: str
    status: str
    problem_id: str | None = None


@dataclass(frozen=True)
class PlanActivated:
    request: RequestDecision
    variant: str
    proposal_id: str | None
    assessable_count: int


@dataclass(frozen=True)
class FeedbackRecorded:
    operation: str
    comfort: str


AdaptiveEffect = ProposalOffered | ProposalResponded | PlanActivated | FeedbackRecorded

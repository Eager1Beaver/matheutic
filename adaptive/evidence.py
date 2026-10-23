"""Pure projection and aggregation of distinct arithmetic problem observations."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, replace

from config import adaptive as settings
from core.constraints import ProblemConstraints

from .models import (
    AttemptFact,
    EvidenceSnapshot,
    EvidenceSummary,
    OperatorSignal,
    ProblemObservation,
)


def context_key(difficulty: int, constraints: ProblemConstraints) -> tuple:
    values = asdict(constraints)
    return difficulty, tuple((k, tuple(v) if isinstance(v, (list, tuple)) else v) for k, v in sorted(values.items()))


def project(snapshot: EvidenceSnapshot, events: tuple) -> EvidenceSnapshot:
    """Include the current turn once, without turning an active problem into a failure."""
    from coach.events import AttemptMade, HintShown, ProblemEnded
    
    current = snapshot.current
    if current is None:
        return snapshot
    
    before_attempted, before_assessable = bool(current.attempts), current.assessable
    for event in events:
        if getattr(event, "problem_id", None) != current.id:
            continue
        if isinstance(event, AttemptMade):
            current = replace(current, attempts=current.attempts + (AttemptFact(
                event.value, event.step_index, event.final, event.correct, event.hints_used),))
        elif isinstance(event, HintShown):
            current = replace(current, hints_used=current.hints_used + int(event.consumes_hint))
        elif isinstance(event, ProblemEnded):
            current = replace(current, status=event.status, end_reason=event.reason)
    
    problems = tuple(p for p in snapshot.problems if p.id != current.id)
    if current.assessable:
        problems = (current,) + problems
    return EvidenceSnapshot(
        snapshot.attempted_count + int(bool(current.attempts)) - int(before_attempted),
        snapshot.assessable_count + int(current.assessable) - int(before_assessable),
        problems, current,
        )


def operand_band(value) -> int:
    maximum = abs(value)
    return next((bound for bound in settings.OPERAND_BANDS if maximum <= bound), int(maximum))


def summarize(
        snapshot: EvidenceSnapshot, 
        difficulty: int, 
        constraints: ProblemConstraints, 
        *, 
        revision: int | None = None,
        ) -> EvidenceSummary:
    """Describe recent comparable outcomes and independently attributable operator evidence."""
    eligible = [p for p in snapshot.problems if p.assessable]
    comparable = [p for p in eligible if context_key(p.difficulty, p.constraints) == context_key(difficulty, constraints)
                  and (revision is None or p.metadata.get("plan_revision") == revision)]
    recent = comparable[:settings.RECENT_WINDOW_PROBLEMS]
    clean = sum(p.clean for p in recent)
    difficult = sum(p.difficult for p in recent)
    pattern = "insufficient"
    
    if len(recent) >= settings.RECENT_WINDOW_PROBLEMS:
        pattern = (
            "strong" if clean / len(recent) >= settings.STRONG_COMPLETION_RATE 
            else "needs_support" 
            if difficult / len(recent) >= settings.SUPPORT_PROBLEM_RATE 
            else "mixed"
            )
    groups = defaultdict(dict)
    recent_ids = {p.id for p in eligible[:settings.RECENT_WINDOW_PROBLEMS]}
    
    for problem in eligible:
        if revision is not None and problem.metadata.get("plan_revision") != revision:
            continue
        
        single = len(problem.analysis.steps) == 1
        indices = {0} if single else {a.step_index for a in problem.attempts if a.step_index is not None}
        for index in indices:
            step = problem.analysis.steps[index]
            band = operand_band(max(abs(step.left), abs(step.right)))
            answers = [a for a in problem.attempts if a.step_index == index or (single and a.step_index is None)]
            wrong = sum(not a.correct for a in answers)
            hard = wrong >= settings.REPEATED_WRONG_ATTEMPTS or (single and problem.status == "revealed")
            key = (step.operation, band)
            groups[key][problem.id] = groups[key].get(problem.id, False) or hard
    
    signals = tuple(
        OperatorSignal(
            op, 
            band, 
            tuple(entries), 
            sum(entries.values()),
            any(pid in recent_ids and hard for pid, hard in entries.items())
            )
            for (op, band), entries in sorted(groups.items())
            )
    return EvidenceSummary(
        snapshot.attempted_count, snapshot.assessable_count,
        "new" if snapshot.attempted_count <= settings.NEW_LEARNER_MAX_PROBLEMS else "established",
        pattern, 
        tuple(p.id for p in recent), 
        clean,
        sum(p.status == "solved" and not p.hints_used for p in recent),
        sum(p.status == "solved" and p.hints_used > 0 for p in recent), 
        difficult,
        sum(p.status == "revealed" for p in recent), 
        sum(p.status == "abandoned" for p in recent),
        len(eligible), 
        signals,
        )

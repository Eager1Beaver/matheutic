"""Coordinate coach turns, explicit practice choices, and projected learner evidence."""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, replace
from uuid import uuid4

from adaptive import messages
from adaptive.evidence import project, summarize
from adaptive.models import (
    AdaptiveDecision,
    AdaptiveEffect,
    FeedbackRecorded,
    PlanActivated,
    PracticeProposal,
    ProposalOffered,
    ProposalResponded,
)
from adaptive.planner import compile_target, resolve_request, target_for
from adaptive.policy import decide
from ai.coach import CoachDecision
from ai.intent import NUMERIC_FIELDS
from config import adaptive as settings

from . import messages as coach_messages
from .events import ProblemEnded, ProblemStarted
from .flow import CoachReply

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedReply:
    reply: CoachReply
    adaptive_effects: tuple[AdaptiveEffect, ...] = ()


def _has_math_choice(request):
    fields = request.diagnostics["interpreted"]
    return bool(
        fields["difficulty"] is not None or 
        fields["difficulty_change"] or 
        fields["allowed_operations"] is not None or 
        fields["required_operations"] or 
        fields["clear_limits"] or 
        any(fields[n] is not None for n in NUMERIC_FIELDS)
        )


def _tag(request, metadata):
    return replace(request, diagnostics=request.diagnostics | {"selection": metadata})


class PracticeApplication:
    """Prepare a reply and its adaptive effects without committing undelivered work."""

    def __init__(self, coach, repository, context):
        self.coach, self.repository, self.context = coach, repository, context
        self.forced = None
        coach.request_resolver = self.resolve

    def resolve(self, session, request, source):
        if self.forced is not None:
            return self.forced
        state = self.context.adaptive_state
        math_choice = _has_math_choice(request)
        fields = request.diagnostics["interpreted"]
        
        metadata = {}
        if source == "learner_repeat":
            metadata = dict(session.practice_metadata)
        elif fields["inherit_previous"] and session.repeat_request is not None:
            metadata = dict(session.practice_metadata)
        elif state.plan is not None and not (state.variant == "foundation_support" and math_choice):
            request = resolve_request(request, state.plan, self.coach.interpreter.constraints)
            if request.intent != "generate_problem":
                return request
            metadata = dict((state.plan.diagnostics or {}).get("selection", {}))
            metadata.update({
                "origin": "foundation_support" 
                if state.variant == "foundation_support" 
                else "adaptive",
                "variant": state.variant, 
                "proposal_id": state.proposal_id, 
                "plan_revision": state.revision,
                "explicit_operations": metadata.get("explicit_operations", False)
                })
        if math_choice and source != "learner_repeat":
            metadata = dict(metadata, origin="learner", proposal_id=None, plan_revision=0, variant="standard")
        
        origin = metadata.get("origin", "learner" if math_choice else "default")
        if source != "learner_repeat" and (fields["allowed_operations"] is not None or fields["required_operations"]):
            metadata["explicit_operations"] = True
        else:
            metadata.setdefault("explicit_operations", False)
        
        metadata.update(
            origin=origin, 
            source="adaptive_recommendation" 
            if origin == "adaptive" 
            else "default" 
            if origin in {"default", "foundation_support"} 
            else source
            )
        metadata.setdefault("variant", "standard")
        metadata.setdefault("plan_revision", 0)
        if source != "learner_repeat":
            inherited_sources = metadata.get("field_sources", {})
            preferences = request.preferences or {}
            metadata["field_sources"] = {
                name: "learner" 
                if fields.get(name) is not None 
                and fields.get(name) != [] 
                or name in fields["clear_limits"] 
                else inherited_sources.get(name, "adaptive" if origin in {"adaptive", "foundation_support"} else "default")
                
                if name in preferences 
                or name == "difficulty" 
                and inherited_sources 
                else "default"
                for name in NUMERIC_FIELDS + ("allowed_operations", "required_operations", "difficulty")
                }
            for name in NUMERIC_FIELDS:
                requested = preferences.get(name)
                effective = getattr(request.constraints, name)
                if requested is not None and requested != effective:
                    metadata["field_sources"][name] = "application_policy"
        return _tag(request, metadata)

    async def prepare(self, session, text, *, on_rejection=None):
        feedback = re.fullmatch(r"\s*(?:i\s+(?:struggle\s+with|find)|(?:i(?:'m| am)\s+)?(?:comfortable|good)\s+(?:with|at))\s+"
                                r"(addition|subtraction|multiplication|division)(?:\s+difficult)?[.!]?\s*", text, re.I)
        if feedback:
            operation = {v: k for k, v in messages.NAMES.items()}[feedback.group(1).lower()]
            comfort = "comfortable" if re.search(r"comfortable|good", text, re.I) else "needs_support"
            effects = [FeedbackRecorded(operation, comfort)] 
            if comfort == "needs_support" and not session.active and session.pending_difficulty is None:
                if session.pending_proposal_id:
                    effects.append(ProposalResponded(session.pending_proposal_id, "superseded"))
                    session.pending_proposal_id = None
                baseline = session.repeat_request or compile_target(self.coach.interpreter.constraints)
                decision = AdaptiveDecision("offer", "focus_operator", "declared_support", operation, 20)
                target = target_for(decision, baseline, self.coach.interpreter.constraints)
                if target is not None:
                    snapshot = await self.repository.learner_evidence(self.context.telegram_user_id)
                    session.repeat_request = baseline
                    p = PracticeProposal(
                        uuid4().hex, 
                        decision.action, decision.reason, 
                        baseline, 
                        target,
                        {"basis": "self_report", "attempted_count": snapshot.attempted_count}, 
                        settings.POLICY_VERSION,
                        )
                    session.pending_proposal_id = p.id
                    effects.append(ProposalOffered(p, snapshot.assessable_count, None))
                    return PreparedReply(CoachReply("clarify", messages.offer(p)), tuple(effects))
            return PreparedReply(
                CoachReply("clarify", "Thanks for telling me. You can ask for the operators and number ranges you prefer."), 
                tuple(effects),
                )

        pending = self.context.proposal if session.pending_proposal_id is not None else None
        decision = None
        if pending is not None:
            baseline = session.repeat_request
            if baseline is None or baseline.constraints != pending.baseline.constraints or baseline.difficulty != pending.baseline.difficulty:
                session.pending_proposal_id = None
                return PreparedReply(
                    CoachReply("clarify", "That suggestion is no longer current. You can request another problem."),
                    (ProposalResponded(pending.id, "expired"),),
                    )
            decision = await self.coach.interpreter.interpret(text, session)
            if decision.intent == "continue":
                bounded = compile_target(
                    self.coach.interpreter.constraints, 
                    level=pending.target.difficulty,
                    operations=pending.target.constraints.allowed_operations,
                    required=pending.target.constraints.required_operations,
                    overrides={n: getattr(pending.target.constraints, n) for n in NUMERIC_FIELDS},
                    )
                if bounded.intent != "generate_problem" or bounded.constraints != pending.target.constraints:
                    session.pending_proposal_id = None
                    return PreparedReply(
                        CoachReply("clarify", "That suggestion no longer fits the current limits. Please request another problem."),
                        (ProposalResponded(pending.id, "expired"),),
                        )
                state = self.context.adaptive_state
                metadata = {
                    "origin": "adaptive", 
                    "source": "adaptive_recommendation", 
                    "variant": "standard",
                    "proposal_id": pending.id, 
                    "plan_revision": state.revision + 1,
                    "explicit_operations": (pending.target.diagnostics or {}).get("selection", {}).get("explicit_operations", False),
                    }
                metadata["field_sources"] = {
                    name: "adaptive" 
                    for name in NUMERIC_FIELDS + ("allowed_operations", "required_operations", "difficulty")
                    }
                self.forced = _tag(pending.target, metadata)
                try:
                    reply = await self.coach.handle(
                        session, 
                        text, 
                        on_rejection=on_rejection,
                        decision=CoachDecision("generate_problem", request=self.forced),
                        )
                finally:
                    self.forced = None
                session.pending_proposal_id = None
                count = (await self.repository.learner_evidence(self.context.telegram_user_id)).assessable_count
                return PreparedReply(
                    reply, 
                    (ProposalResponded(pending.id, "accepted", session.run.problem_id),
                    PlanActivated(session.repeat_request, "standard", pending.id, count)),
                    )
            if decision.intent == "decline":
                session.pending_proposal_id = None
                return PreparedReply(
                    CoachReply("decline", messages.KEEP_SETTINGS), 
                    (ProposalResponded(pending.id, "declined"),),
                    )
        
        reply = await self.coach.handle(session, text, on_rejection=on_rejection, decision=decision)
        if pending is not None and (reply.generated is not None or session.pending_difficulty is not None or reply.intent == "stop"):
            session.pending_proposal_id = None
            return PreparedReply(
                reply, 
                (ProposalResponded(pending.id, "expired" if reply.intent == "stop" else "superseded"),),
                )
        return await self.evaluate(session, reply)

    async def evaluate(self, session, reply):
        """Evaluate the projected completed turn and append at most one explicit offer."""
        if (
            session.active 
            or session.pending_difficulty is not None 
            or session.pending_proposal_id is not None
            or reply.intent == "stop" 
            or not any(isinstance(e, ProblemEnded) for e in reply.events)
            or session.repeat_request is None
            ):
            return PreparedReply(reply)
        snapshot = await self.repository.learner_evidence(self.context.telegram_user_id, session.run.problem_id)
        snapshot = project(snapshot, reply.events)
        state, request = self.context.adaptive_state, session.repeat_request
        metadata = session.practice_metadata
        revision = state.revision if state.plan is not None and metadata.get("plan_revision") == state.revision else None
        evidence = summarize(snapshot, request.difficulty, request.constraints, revision=revision)
        decision = decide(
            evidence, 
            state, 
            difficulty=request.difficulty, 
            default_practice=metadata.get("origin") == "default",
            variant=metadata.get("variant", "standard"), 
            operators=request.constraints.allowed_operations,
            )
        logger.info(
            "Adaptive assessment: experience=%s recent=%s samples=%s lifetime=%s decision=%s reason=%s policy=%s",
            evidence.experience, evidence.recent_pattern, len(evidence.recent_ids), evidence.attempted_count,
            decision.kind, decision.reason, 
            settings.POLICY_VERSION,
            )
        if decision.kind == "hold":
            return PreparedReply(reply)
        target = target_for(decision, request, self.coach.interpreter.constraints)
        if target is None:
            return PreparedReply(reply)
        if decision.kind == "foundation_support":
            target = _tag(
                target, 
                {
                    "origin": "foundation_support", 
                    "source": "default", 
                    "variant": "foundation_support",
                    "plan_revision": state.revision + 1, 
                    "explicit_operations": False,
                    "field_sources": {name: "adaptive" for name in NUMERIC_FIELDS + ("allowed_operations", "required_operations", "difficulty")},
                    },
                    )
            session.repeat_request = target
            session.practice_metadata = target.diagnostics["selection"]
            return PreparedReply(
                reply, 
                (PlanActivated(target, "foundation_support", None, evidence.assessable_count),),
                )
        p = PracticeProposal(
            uuid4().hex, 
            decision.action, decision.reason, 
            request, target, 
            asdict(evidence), 
            settings.POLICY_VERSION,
            )
        session.pending_proposal_id = p.id
        text = (reply.text or "").replace(coach_messages.NEXT_PROBLEM, "").rstrip()
        return PreparedReply(
            replace(reply, text=text + "\n\n" + messages.offer(p)),
            (ProposalOffered(p, evidence.assessable_count, session.run.problem_id),),
            )

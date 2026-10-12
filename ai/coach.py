"""State-aware intent interpretation with local conversational shortcuts."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from fractions import Fraction

from coach.answers import explicit_final_answer, parse_answer
from coach.session import CoachSession
from core.constraints import ProblemConstraints
from core.problem_validator import ValidationIssue

from .errors import RequestInterpretationInvalid
from .intent import RequestDecision, compile_decision
from .policy import natural_number_policy
from .provider import AIProvider
from .request_checks import source_request_issue

# TODO: explore spacy / NLTK, 
# such hardcoded actions are not very practical on a bigger scale
# plus it complicates localization 
# TODO: consider when introduce other languages
_LOCAL_ACTIONS = {
    "continue": {"yes", "yes please", "yep", "yeah", "sure", "okay", "ok", "please do"},
    "decline": {"no", "nope", "no thanks", "no thank you", "not now"},
    "request_hint": {"hint", "a hint", "hint please", "please give me a hint", "help", "help please", "another hint", "next hint", "give me a hint"},
    "repeat_hint": {"repeat hint", "repeat the hint", "same hint", "repeat that hint"},
    "repeat_problem": {"another", "another one", "another problem", "next", "next problem", "give me another problem", "give me another one"},
    "give_up": {"give up", "i give up", "show me the answer", "what is the answer", "show me the solution", "solution", "answer please"},
    "stop": {"stop", "finish", "that's enough", "that is enough", "stop practising", "stop practicing"},
    "explain": {"why", "i don't understand", "i don't understand the hint"},
    }
_GREETING = re.compile(r"(?:hi|hello|hey|good morning|good afternoon|good evening)[!.,\s]*", re.I)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CoachDecision:
    intent: str
    reason: str = "none"
    value: Fraction | None = None
    final_answer: bool = False
    request: RequestDecision | None = None


def session_context(session: CoachSession) -> dict:
    """Build a bounded context without the expected numerical answer."""
    payload = {"state": session.state.value, "active_problem": session.active}
    if session.repeat_request is not None:
        payload["previous_request"] = {
            "preferences": session.repeat_request.preferences or {},
            "difficulty": session.repeat_request.difficulty,
            }
        payload["previous_request"]["language"] = session.language
    if session.pending_difficulty is not None:
        pending = session.pending_difficulty
        payload["pending_difficulty"] = {
            "choice": pending.kind, 
            "target_level": pending.request.difficulty,
            "same_operators": pending.same_operations,
            "next_operators": pending.request.constraints.allowed_operations,
            }
    if session.run is not None:
        run = session.run
        payload["statement"] = run.validated.problem.statement
        payload["answer_target"] = "current" if run.step_index is not None else "final"
        if run.step_index is not None:
            step = run.validated.analysis.steps[run.step_index]
            payload["current_calculation"] = f"{step.left} {step.operation} {step.right}"
        payload["last_hint"] = run.last_hint
        payload["recent_turns"] = list(run.recent_turns)
        payload["outcome"] = run.outcome
    return payload


class CoachInterpreter:
    """Route learner actions and compile new requests against application constraints."""

    def __init__(self, provider: AIProvider, constraints: ProblemConstraints | None = None, *, dev_mode: bool = False) -> None:
        self.provider = provider
        self.constraints = natural_number_policy(constraints)
        self.dev_mode = dev_mode

    async def interpret(self, text: str, session: CoachSession) -> CoachDecision:
        """Use local parsing first and one structured provider call for complex turns."""
        text = text.strip()
        if not text or len(text) > 4000:
            return CoachDecision("clarify", "unclear")
        value = parse_answer(text)
        if value is not None:
            return CoachDecision("answer", value=value, final_answer=explicit_final_answer(text))
        normalized = " ".join(text.lower().rstrip("!?.").split())
        for intent, forms in _LOCAL_ACTIONS.items():
            if normalized in forms:
                return CoachDecision(intent)
        if _GREETING.fullmatch(text):
            return CoachDecision("off_topic", "greeting")
        if issue := source_request_issue(text):
            return CoachDecision("unsupported_request", issue)

        relative = re.fullmatch(r"(?:(?:another(?: one| problem)?|next(?: problem)?)[, ]+(?:but )?)?(harder|easier)(?: please)?", normalized)
        if relative:
            from .intent import NUMERIC_FIELDS
            from .schemas import ProblemRequest, RequestInterpretation
            spec = ProblemRequest(
                **{name: None for name in NUMERIC_FIELDS}, 
                allowed_operations=None, required_operations=[],
                difficulty=None, difficulty_change=1 if relative.group(1) == "harder" else -1,
                inherit_previous=session.repeat_request is not None, unresolved=False, 
                clear_limits=[],
                language=session.language, theme=None, style=None,
                )
            request = compile_decision(
                RequestInterpretation(
                    intent="generate_problem", 
                    reason="none", 
                    problem_request=spec
                    ),
                    self.constraints, 
                    previous_request=session_context(session).get("previous_request"),
                    )
            return CoachDecision(request.intent, request.reason, request=request)

        from pydantic import ValidationError

        from .schemas import CoachInterpretation, RequestInterpretation

        payload = json.dumps({"context": session_context(session), "message": text}, ensure_ascii=False, separators=(",", ":"))
        interpretation = await self.provider.interpret_turn(request=payload, language=session.language, dev_mode=self.dev_mode)
        try:
            interpretation = CoachInterpretation.model_validate(
                interpretation.model_dump() if isinstance(interpretation, CoachInterpretation) else interpretation
                )
        except ValidationError as error:
            raise RequestInterpretationInvalid([
                ValidationIssue("invalid_coach_action", "The provider returned an inconsistent coach action.")
                ]) from error
        if interpretation.intent == "answer":
            quote = interpretation.answer_text.strip()
            value = parse_answer(quote)
            if not quote or not re.search(r"(?<!\w)" + re.escape(quote) + r"(?!\w)", text, re.I) or value is None:
                return CoachDecision("clarify", "unclear")
            return CoachDecision("answer", value=value, final_answer=interpretation.answer_target == "final")
        if interpretation.intent in {"generate_problem", "unsupported_request", "off_topic", "clarify"}:
            previous = session_context(session).get("previous_request")
            if interpretation.intent == "generate_problem" and session.pending_difficulty is not None:
                spec = interpretation.problem_request
                if spec.difficulty is None and spec.difficulty_change == 0:
                    pending = session.pending_difficulty.request
                    previous = {"difficulty": pending.difficulty, "preferences": pending.preferences or {}}
                    interpretation = interpretation.model_copy(update={"problem_request": spec.model_copy(update={"inherit_previous": True})})
            request = compile_decision(
                RequestInterpretation(
                    intent=interpretation.intent, 
                    reason=interpretation.reason,
                    problem_request=interpretation.problem_request,
                    ), 
                    self.constraints, 
                    source_text=text,
                    previous_request=previous,
                    )
            if self.dev_mode and request.constraints is not None:
                logger.info(
                    "Compiled arithmetic request: constraints=%s explicit_fields=%s",
                    request.constraints, 
                    list(request.preferences or {}),
                    )
            return CoachDecision(request.intent, request.reason, request=request)
        return CoachDecision(interpretation.intent)

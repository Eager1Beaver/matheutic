"""Route learner messages and compile arithmetic requests into validated policies."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from core.constraints import SUPPORTED_OPERATIONS, ProblemConstraints
from core.problem_validator import ValidationIssue

from .errors import RequestInterpretationInvalid, UnsupportedProblemRequest
from .policy import natural_number_policy

if TYPE_CHECKING:
    from .provider import AIProvider
    from .schemas import ProblemRequest, RequestInterpretation

logger = logging.getLogger(__name__)

_ROUTE_REASONS = {
    "generate_problem": {"none"},
    "unsupported_request": {
        "unsupported_math", "unsupported_task", 
        "impossible_constraints", "invalid_instructions", 
        "unsupported_language", 
        },
    "off_topic": {"off_topic", "greeting"},
    "clarify": {"unclear", "answer_without_problem"},
    }
_GREETING = re.compile(r"(?:hi|hello|hey|good morning|good afternoon|good evening)[!.,\s]*", re.I)
_ANSWER = re.compile(r"[+-]?[0-9]+(?:[.,][0-9]+)?\??")


@dataclass(frozen=True)
class RequestDecision:
    intent: str
    reason: str
    generation_request: str | None = None
    constraints: ProblemConstraints | None = None
    difficulty: int | None = None
    language: str = "en"


def _smaller_limit(first: int | None, second: int | None) -> int | None:
    """Intersect optional upper bounds, retaining an existing limit."""
    if first is None:
        return second
    if second is None:
        return first
    return min(first, second)


def compile_constraints(spec: ProblemRequest, base: ProblemConstraints) -> ProblemConstraints:
    """Intersect interpreted arithmetic requirements with the application's policy."""
    try:
        requested = ProblemConstraints(
            allowed_operations=spec.allowed_operations, required_operations=spec.required_operations,
            min_operand=spec.min_operand, max_operand=spec.max_operand,
            min_operations=spec.min_operations, max_operations=spec.max_operations,
            require_integer_division=True,
            non_negative=True, non_negative_intermediate=True,
            max_intermediate_value=spec.max_intermediate_value, max_final_value=spec.max_final_value,
            )
        allowed = tuple(op for op in SUPPORTED_OPERATIONS
                        if op in base.allowed_operations and op in requested.allowed_operations)
        required = tuple(op for op in SUPPORTED_OPERATIONS
                         if op in base.required_operations or op in requested.required_operations)
        policy = ProblemConstraints(
            allowed_operations=allowed, required_operations=required,
            min_operand=max(base.min_operand, requested.min_operand),
            max_operand=min(base.max_operand, requested.max_operand),
            min_operations=max(base.min_operations, requested.min_operations),
            max_operations=min(base.max_operations, requested.max_operations),
            require_integer_division=True,
            non_negative=base.non_negative or requested.non_negative,
            non_negative_intermediate=base.non_negative_intermediate or requested.non_negative_intermediate,
            max_intermediate_value=_smaller_limit(base.max_intermediate_value, requested.max_intermediate_value),
            max_final_value=_smaller_limit(base.max_final_value, requested.max_final_value),
            )
    except ValueError as error:
        logger.warning("Rejected arithmetic request constraints: %s", error)
        raise UnsupportedProblemRequest(
            "The arithmetic requirements conflict with the supported policy.", reason="impossible_constraints"
            ) from error
    if policy.max_operand == 0 and (
        "/" in policy.required_operations or policy.allowed_operations == ("/",)
        ):
        logger.warning("Rejected arithmetic request constraints: division requires a non-zero divisor")
        raise UnsupportedProblemRequest("Division cannot use only zero operands.", reason="impossible_constraints")
    return policy


def compile_decision(interpretation: RequestInterpretation, base: ProblemConstraints) -> RequestDecision:
    """Check routing invariants and build a canonical generation request."""
    if (interpretation.intent not in _ROUTE_REASONS
            or interpretation.reason not in _ROUTE_REASONS[interpretation.intent]
            or ((interpretation.intent == "generate_problem") != (interpretation.problem_request is not None))):
        raise RequestInterpretationInvalid([
            ValidationIssue("inconsistent_route", "The interpreter returned an inconsistent routing decision.")
            ])
    if interpretation.intent != "generate_problem":
        return RequestDecision(interpretation.intent, interpretation.reason)
    spec = interpretation.problem_request
    # TODO: other languages will be supported; maybe pass a list of supported ones
    # and an error will be raised specifying supported language
    if spec.language != "en":
        return RequestDecision("unsupported_request", "unsupported_language")
    try:
        policy = compile_constraints(spec, base)
    except UnsupportedProblemRequest as error:
        return RequestDecision("unsupported_request", error.reason)
    bounds = {key: value for key, value in asdict(policy).items() if value is not None}
    # Integer division and non-negative values are fixed generation rules.
    for key in ("require_integer_division", "non_negative", "non_negative_intermediate"):
        bounds.pop(key)
    payload = {"constraints": bounds}
    if spec.difficulty is not None:
        payload["difficulty"] = spec.difficulty
    if spec.context:
        payload["context"] = spec.context
    request = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return RequestDecision("generate_problem", "none", request, policy, spec.difficulty, spec.language)


class RequestInterpreter:
    """Classify messages before arithmetic generation and enforce the application policy."""

    def __init__(
            self, 
            provider: AIProvider, 
            constraints: ProblemConstraints | None = None,
            *, 
            dev_mode: bool = False,
            ) -> None:
        if type(dev_mode) is not bool:
            raise ValueError("dev_mode must be a boolean")
        self.provider = provider
        self.constraints = natural_number_policy(constraints)
        self.dev_mode = dev_mode

    async def interpret(self, request: str) -> RequestDecision:
        """Handle simple messages locally and classify other text through the provider."""
        text = request.strip()
        if not text:
            return RequestDecision("clarify", "unclear")
        if len(text) > 4000:
            return RequestDecision("clarify", "unclear")
        if _GREETING.fullmatch(text):
            return RequestDecision("off_topic", "greeting")
        if _ANSWER.fullmatch(text):
            return RequestDecision("clarify", "answer_without_problem")
        interpretation = await self.provider.interpret_request(
            request=text, language="en", dev_mode=self.dev_mode,
            )
        return compile_decision(interpretation, self.constraints)

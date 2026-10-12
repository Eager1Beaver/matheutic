"""Route learner messages and compile explicit preferences with difficulty presets."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

from config.difficulty import DEFAULT_DIFFICULTY, difficulty_preset
from core.constraints import SUPPORTED_OPERATIONS, ProblemConstraints
from core.problem_validator import ValidationIssue

from .errors import RequestInterpretationInvalid, UnsupportedProblemRequest
from .policy import natural_number_policy
from .request_scope import custom_problem_request

_ROUTE_REASONS = {
    "generate_problem": {"none"},
    "unsupported_request": {
        "unsupported_math", "unsupported_task", "impossible_constraints",
        "invalid_instructions", "unsupported_language", "unsupported_custom_problem",
        },
    "off_topic": {"off_topic", "greeting"},
    "clarify": {"unclear", "answer_without_problem"},
}
_GREETING = re.compile(r"(?:hi|hello|hey|good morning|good afternoon|good evening)[!.,\s]*", re.I)
_ANSWER = re.compile(r"[+-]?[0-9]+(?:[.,][0-9]+)?\??")
NUMERIC_FIELDS = (
    "min_operand", "max_operand", "min_operations", "max_operations",
    "min_intermediate_value", "max_intermediate_value", "min_final_value", "max_final_value",
    )


@dataclass(frozen=True)
class RequestDecision:
    intent: str
    reason: str
    generation_request: str | None = None
    constraints: ProblemConstraints | None = None
    difficulty: int | None = None
    language: str = "en"
    diagnostics: dict | None = None
    preferences: dict | None = None


def _resolve(spec, previous: dict | None):
    fields = spec.model_dump() if hasattr(spec, "model_dump") else vars(spec).copy()
    fields["required_operations"] = fields["required_operations"] or []
    fields["clear_limits"] = fields["clear_limits"] or []
    inherited = previous if fields["inherit_previous"] and previous else {}
    preferences = dict(inherited.get("preferences", {}))
    level = fields["difficulty"] if fields["difficulty"] is not None else inherited.get("difficulty", DEFAULT_DIFFICULTY)
    level = max(1, min(5, level + fields["difficulty_change"]))
    for name in NUMERIC_FIELDS + ("allowed_operations", "theme", "style"):
        value = fields[name]
        if value is not None and value != "":
            preferences[name] = value
    if fields["allowed_operations"] is not None or fields["required_operations"]:
        preferences["required_operations"] = fields["required_operations"]
    cleared = set(preferences.get("clear_limits", []))
    cleared.difference_update(name for name in NUMERIC_FIELDS if fields[name] is not None)
    cleared.update(fields["clear_limits"])
    for name in fields["clear_limits"]:
        preferences.pop(name, None)
    preferences["clear_limits"] = sorted(cleared)
    defaults = asdict(difficulty_preset(level))
    custom_scale = (
        any(name in preferences for name in ("min_operand", "max_operand"))
        or preferences.get("min_operations", defaults["min_operations"]) > defaults["max_operations"]
        or preferences.get("max_operations", defaults["max_operations"]) > defaults["max_operations"]
        )
    if custom_scale:
        defaults["max_intermediate_value"] = defaults["max_final_value"] = None
    values = defaults | {name: value for name, value in preferences.items() if name in defaults}
    if "min_operand" in preferences and "max_operand" not in preferences:
        values["max_operand"] = min(10**9, max(values["max_operand"], values["min_operand"] * 10))
    if "min_operations" in preferences and "max_operations" not in preferences:
        values["max_operations"] = max(values["min_operations"], values["max_operations"])
    if "max_operations" in preferences and "min_operations" not in preferences:
        values["min_operations"] = min(values["min_operations"], values["max_operations"])
    for kind in ("intermediate", "final"):
        lower, upper = f"min_{kind}_value", f"max_{kind}_value"
        if lower in preferences and upper not in preferences and values[upper] is not None and values[lower] > values[upper]:
            values[upper] = None
    for name in cleared:
        values[name] = None
    required = preferences.get("required_operations", [])
    if "allowed_operations" not in preferences:
        values["allowed_operations"] = [op for op in SUPPORTED_OPERATIONS if op in set(values["allowed_operations"]) | set(required)]
    values["required_operations"] = required
    return fields, preferences, level, values


def compile_constraints(spec, base: ProblemConstraints) -> ProblemConstraints:
    """Combine a fresh preference request with application-owned hard limits."""
    return _policy(_resolve(spec, None)[3], base)


def _policy(values: dict, base: ProblemConstraints) -> ProblemConstraints:
    try:
        values = dict(values)
        values["allowed_operations"] = tuple(op for op in SUPPORTED_OPERATIONS if op in values["allowed_operations"] and op in base.allowed_operations)
        values["required_operations"] = tuple(op for op in SUPPORTED_OPERATIONS if op in values["required_operations"] or op in base.required_operations)
        for lower, upper in (("min_operand", "max_operand"), ("min_operations", "max_operations"),
                             ("min_intermediate_value", "max_intermediate_value"), ("min_final_value", "max_final_value")):
            base_lower, base_upper = getattr(base, lower), getattr(base, upper)
            if base_lower is not None:
                values[lower] = base_lower if values[lower] is None else max(values[lower], base_lower)
            if base_upper is not None:
                values[upper] = base_upper if values[upper] is None else min(values[upper], base_upper)
        values["min_operations"] = max(values["min_operations"], len(values["required_operations"]))
        policy = ProblemConstraints(**values, non_negative=True, non_negative_intermediate=True,
                                    require_integer_division=True, intermediate_includes_final=False)
        if policy.max_operand == 0 and "/" in policy.required_operations:
            raise ValueError("Division requires a nonzero divisor")
        if policy.max_operand == 0 and policy.allowed_operations == ("/",):
            raise ValueError("Division requires a nonzero divisor")
        return policy
    except ValueError as error:
        raise UnsupportedProblemRequest(reason="impossible_constraints") from error


def compile_decision(interpretation, base: ProblemConstraints, *, source_text: str | None = None,
                     previous_request: dict | None = None) -> RequestDecision:
    """Resolve relative preferences and produce a reproducible arithmetic policy."""
    if (interpretation.intent not in _ROUTE_REASONS
            or interpretation.reason not in _ROUTE_REASONS[interpretation.intent]
            or ((interpretation.intent == "generate_problem") != (interpretation.problem_request is not None))):
        raise RequestInterpretationInvalid([ValidationIssue("inconsistent_route", "The interpreter returned an inconsistent routing decision.")])
    if interpretation.intent != "generate_problem":
        return RequestDecision(interpretation.intent, interpretation.reason)
    if source_text and custom_problem_request(source_text):
        return RequestDecision("unsupported_request", "unsupported_custom_problem")
    spec = interpretation.problem_request
    # TODO: other languages will be supported; maybe pass a list of supported ones
    # and an error will be raised specifying supported language
    if spec.language != "en":
        return RequestDecision("unsupported_request", "unsupported_language")
    if spec.unresolved:
        return RequestDecision("clarify", "unclear")
    fields, preferences, level, values = _resolve(spec, previous_request)
    try:
        policy = _policy(values, base)
    except UnsupportedProblemRequest as error:
        return RequestDecision("unsupported_request", error.reason)
    effective = asdict(policy)
    payload = {"constraints": effective, "difficulty": level,
               "theme": preferences.get("theme", ""), "style": preferences.get("style", "")}
    diagnostics = {"interpreted": fields, "explicit": preferences, "effective": effective,
                   "preset": level}
    return RequestDecision("generate_problem", "none", json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
                           policy, level, spec.language, diagnostics, preferences)


class RequestInterpreter:
    """Classify learner requests before compiling application-owned practice policies."""
    def __init__(self, provider, constraints: ProblemConstraints | None = None, *, dev_mode: bool = False):
        if type(dev_mode) is not bool:
            raise ValueError("dev_mode must be a boolean")
        self.provider = provider
        self.constraints = natural_number_policy(constraints)
        self.dev_mode = dev_mode

    async def interpret(self, request: str) -> RequestDecision:
        text = request.strip()
        if not text or len(text) > 4000:
            return RequestDecision("clarify", "unclear")
        if _GREETING.fullmatch(text):
            return RequestDecision("off_topic", "greeting")
        if _ANSWER.fullmatch(text):
            return RequestDecision("clarify", "answer_without_problem")
        interpretation = await self.provider.interpret_request(request=text, language="en", dev_mode=self.dev_mode)
        return compile_decision(interpretation, self.constraints, source_text=text)

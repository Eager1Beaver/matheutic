"""Versioned JSON checkpoints with exact arithmetic and validated recovery."""
from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import asdict
from fractions import Fraction

from ai.intent import RequestDecision
from ai.orchestrator import ValidatedProblem
from coach.session import (
    AnswerAttempt,
    CoachSession,
    CoachState,
    DifficultyChoice,
    ProblemRun,
)
from config.difficulty import MAX_PROGRESSIVE_DIFFICULTY
from config.preferences import UserPreferences
from core.constraints import ProblemConstraints
from core.problem_validator import validate_problem

from .errors import StateRecoveryError

CHECKPOINT_VERSION = 2


def json_text(value) -> str:
    """Encode finite JSON values without rounding integer quantities."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def exact(value: Fraction | int) -> dict[str, str]:
    """Represent an exact number as decimal numerator and denominator strings."""
    value = Fraction(value)
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def read_exact(value: dict) -> Fraction:
    """Validate and reconstruct a bounded canonical rational number."""
    _keys(value, {"numerator", "denominator"})
    for field in value.values():
        if not isinstance(field, str) or not re.fullmatch(r"-?(?:0|[1-9][0-9]{0,1233})", field):
            raise ValueError("Invalid exact number")
    numerator, denominator = int(value["numerator"]), int(value["denominator"])
    if denominator <= 0 or max(abs(numerator).bit_length(), denominator.bit_length()) > 4096:
        raise ValueError("Exact number exceeds its storage limit")
    result = Fraction(numerator, denominator)
    if exact(result) != value:
        raise ValueError("Exact number is not canonical")
    return result


def request_data(request: RequestDecision | None) -> dict | None:
    """Serialize a structured request independently of current difficulty defaults."""
    return asdict(request) if request is not None else None


def _keys(value, keys: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("Unexpected checkpoint fields")


def _integer(value, minimum: int = 0, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError("Invalid checkpoint counter")
    return value


def _optional_index(value, count: int) -> int | None:
    return None if value is None else _integer(value, 0, count - 1)


def _request(value) -> RequestDecision | None:
    if value is None:
        return None
    
    _keys(value, set(RequestDecision.__dataclass_fields__))
    if value["intent"] != "generate_problem" or value["reason"] != "none":
        raise ValueError("A retained request must generate a problem")
    
    constraints = ProblemConstraints(**value["constraints"])
    _integer(value["difficulty"], 1, MAX_PROGRESSIVE_DIFFICULTY)
    _integer(abs(value["difficulty_change"]))
    if type(value["difficulty_change"]) is not int:
        raise ValueError("Invalid difficulty change")
    
    UserPreferences(content_language=value["language"])
    if not isinstance(value["generation_request"], str):
        raise TypeError("Invalid generation request")
    
    if not isinstance(value["preferences"], dict) or not isinstance(value["diagnostics"], dict):
        raise TypeError("Invalid request metadata")
    interpreted = value["diagnostics"].get("interpreted")
    
    if not isinstance(interpreted, dict):
        raise TypeError("Missing interpreted request")
    
    from ai.schemas import ProblemRequest
    ProblemRequest.model_validate(interpreted)
    return RequestDecision(**(value | {"constraints": constraints}))


def encode_session(session: CoachSession) -> str:
    """Serialize a coach checkpoint with its bounded interpretation context."""
    run = session.run
    run_data = None
    if run is not None:
        validated = run.validated
        run_data = {
            "problem_id": run.problem_id,
            "validated": {
                "problem": validated.problem.model_dump(),
                "constraints": asdict(validated.constraints) if validated.constraints is not None else None,
                "attempts": validated.attempts,
                "request_diagnostics": validated.request_diagnostics,
                "story_review": validated.story_review.model_dump() if validated.story_review is not None else None,
                "story_review_attempts": validated.story_review_attempts,
                },
            "attempts": run.attempts, 
            "final_attempts": run.final_attempts,
            "recent_attempts": [
                {"value": exact(a.value), "step_index": a.step_index, "correct": a.correct}
                for a in run.recent_attempts
                ],
            "hints_used": run.hints_used, "hint_level": run.hint_level,
            "step_index": run.step_index, "steps_solved": run.steps_solved,
            "last_hint": run.last_hint, 
            "outcome": run.outcome,
            "recent_turns": list(run.recent_turns),
            }
    choice = session.pending_difficulty
    return json_text({
        "version": CHECKPOINT_VERSION, 
        "state": session.state.value,
        "run": run_data, 
        "repeat_request": request_data(session.repeat_request),
        "difficulty": session.difficulty, 
        "language": session.language,
        "pending_proposal_id": session.pending_proposal_id,
        "practice_metadata": session.practice_metadata,
        "pending_difficulty": None if choice is None else {
            "request": request_data(choice.request), 
            "kind": choice.kind,
            "same_operations": choice.same_operations, 
            "same_required": choice.same_required,
            },
            })


def _load_run(value: dict) -> ProblemRun:
    from ai.schemas import MathProblem, StoryReview

    _keys(value, set(ProblemRun.__dataclass_fields__))
    if not isinstance(value["problem_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", value["problem_id"]):
        raise ValueError("Invalid problem identity")
    
    record = value["validated"]
    _keys(record, {
        "problem", 
        "constraints", 
        "attempts", 
        "request_diagnostics", 
        "story_review", 
        "story_review_attempts",
        })
    problem = MathProblem.model_validate(record["problem"])
    constraints = ProblemConstraints(**record["constraints"]) if record["constraints"] is not None else None
    analysis = validate_problem(problem, constraints)
    validated = ValidatedProblem(
        problem=problem, 
        analysis=analysis,
        attempts=_integer(record["attempts"], 1, 5), 
        constraints=constraints,
        request_diagnostics=record["request_diagnostics"],
        story_review=StoryReview.model_validate(record["story_review"]) if record["story_review"] is not None else None,
        story_review_attempts=_integer(record["story_review_attempts"]),
        )
    count = len(analysis.steps)
    attempts = _integer(value["attempts"])
    final_attempts = _integer(value["final_attempts"], 0, attempts)
    if not isinstance(value["recent_attempts"], list) or len(value["recent_attempts"]) != min(attempts, 20):
        raise ValueError("Invalid recent attempts")
    
    recent = deque(maxlen=20)
    for entry in value["recent_attempts"]:
        _keys(entry, {"value", "step_index", "correct"})
        answer = read_exact(entry["value"])
        index = _optional_index(entry["step_index"], count)
        expected = analysis.value if index is None else analysis.steps[index].result
        if type(entry["correct"]) is not bool or entry["correct"] != (answer == expected):
            raise ValueError("Invalid answer grading")
        recent.append(AnswerAttempt(answer, index, entry["correct"]))
    
    if value["outcome"] not in {None, "solved", "revealed", "stopped"}:
        raise ValueError("Invalid problem outcome")
    
    if value["last_hint"] is not None and (not isinstance(value["last_hint"], str) or len(value["last_hint"]) > 8000):
        raise ValueError("Invalid saved hint")
    
    turns = value["recent_turns"]
    if not isinstance(turns, list) or len(turns) > 8:
        raise ValueError("Invalid conversation context")
    
    for turn in turns:
        _keys(turn, {"role", "text"})
        if turn["role"] not in {"learner", "coach"} or not isinstance(turn["text"], str) or len(turn["text"]) > 500:
            raise ValueError("Invalid conversation excerpt")
    
    return ProblemRun(
        validated=validated, 
        problem_id=value["problem_id"], 
        attempts=attempts,
        final_attempts=final_attempts, 
        recent_attempts=recent,
        hints_used=_integer(value["hints_used"]), 
        hint_level=_integer(value["hint_level"], 0, 4),
        step_index=_optional_index(value["step_index"], count),
        steps_solved=_integer(value["steps_solved"], 0, count),
        last_hint=value["last_hint"], 
        outcome=value["outcome"], 
        recent_turns=deque(turns, maxlen=8),
        )


def decode_session(raw: str) -> CoachSession:
    """Validate saved state and rederive its mathematics without a provider call."""
    try:
        if not isinstance(raw, str) or len(raw) > 1_000_000:
            raise ValueError("Invalid checkpoint size")
        
        value = json.loads(raw)
        if isinstance(value, dict) and type(value.get("version")) is int and value["version"] == 1:
            value = value | {"version": CHECKPOINT_VERSION, "pending_proposal_id": None, "practice_metadata": {}}
        _keys(value, {
            "version", 
            "state", 
            "run", 
            "repeat_request", 
            "difficulty", 
            "language", 
            "pending_difficulty",
            "pending_proposal_id",
            "practice_metadata",
            })
        
        if type(value["version"]) is not int or value["version"] != CHECKPOINT_VERSION:
            raise ValueError("Unsupported checkpoint version")
        
        UserPreferences(content_language=value["language"])
        difficulty = value["difficulty"]
        if difficulty is not None:
            _integer(difficulty, 1, MAX_PROGRESSIVE_DIFFICULTY)
        
        choice = value["pending_difficulty"]
        pending = None
        if choice is not None:
            _keys(choice, set(DifficultyChoice.__dataclass_fields__))
            if choice["kind"] not in {"operators", "limits", "custom_limits"}:
                raise ValueError("Invalid difficulty choice")
            
            request = _request(choice["request"])
            if request is None:
                raise ValueError("Missing pending request")
            
            ProblemConstraints(
                allowed_operations=choice["same_operations"] if choice["same_operations"] is not None else request.constraints.allowed_operations,
                required_operations=choice["same_required"],
                )
            pending = DifficultyChoice(
                request, 
                choice["kind"],
                tuple(choice["same_operations"]) if choice["same_operations"] is not None else None,
                tuple(choice["same_required"]),
                )
        session = CoachSession(
            state=CoachState(value["state"]), 
            run=_load_run(value["run"]) if value["run"] is not None else None,
            repeat_request=_request(value["repeat_request"]), 
            difficulty=difficulty,
            language=value["language"], 
            pending_difficulty=pending,
            pending_proposal_id=value["pending_proposal_id"],
            practice_metadata=value["practice_metadata"],
            )
        if not isinstance(session.practice_metadata, dict):
            raise ValueError("Invalid practice provenance")
        if session.pending_proposal_id is not None:
            if (not isinstance(session.pending_proposal_id, str) or not re.fullmatch(r"[0-9a-f]{32}", session.pending_proposal_id)
                    or session.active or session.pending_difficulty is not None):
                raise ValueError("Invalid pending practice proposal")
        if session.state in {CoachState.AWAITING_ANSWER, CoachState.OFFERING_HINT} and not session.active:
            raise ValueError("An awaiting state needs an active problem")
        if session.state == CoachState.PROBLEM_COMPLETE and (session.run is None or session.run.outcome not in {"solved", "revealed"}):
            raise ValueError("A completed state needs a completed problem")
        if session.run is not None:
            if session.difficulty != session.run.validated.problem.difficulty or session.language != session.run.validated.problem.language:
                raise ValueError("Problem and session settings disagree")
            if session.state == CoachState.IDLE and session.run.outcome is None:
                raise ValueError("An idle session cannot hide an active problem")
        return session
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError) as error:
        raise StateRecoveryError("Saved practice state failed validation. Use /start to begin a new session.") from error

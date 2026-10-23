"""Compile complete adaptive targets through the normal arithmetic request policy."""
from __future__ import annotations

import random
from dataclasses import asdict, replace

from ai.errors import GenerationExhausted
from ai.intent import NUMERIC_FIELDS, RequestDecision, compile_decision
from config.adaptive import FOUNDATION_MAX_VALUE
from config.difficulty import practice_preset


def compile_target(base, *, level=1, operations=None, required=None, overrides=None, theme="", style="") -> RequestDecision:
    from ai.schemas import ProblemRequest, RequestInterpretation
    values = asdict(practice_preset(level))
    values.pop("preferred_operations")
    if operations is not None:
        values["allowed_operations"] = list(operations)
    else:
        values["allowed_operations"] = list(values["allowed_operations"])
    values["required_operations"] = list(required or ())
    values.update(overrides or {})
    spec = ProblemRequest(
        **values, 
        difficulty=level if level <= 5 else None, 
        difficulty_change=0,
        inherit_previous=level > 5, 
        unresolved=False, 
        clear_limits=[], 
        language="en", 
        theme=theme, 
        style=style,
        )
    return compile_decision(
        RequestInterpretation(intent="generate_problem", reason="none", problem_request=spec), 
        base,
        previous_request={"difficulty": level, "preferences": {}} if level > 5 else None
        )


def target_for(decision, baseline, base):
    """Return a feasible changed target, or abstain without changing current settings."""
    level, policy = baseline.difficulty, baseline.constraints
    metadata = (baseline.diagnostics or {}).get("selection", {})
    explicit_ops = metadata.get(
        "explicit_operations", 
        bool(
            (baseline.preferences or {}).get("allowed_operations") or 
            (baseline.preferences or {}).get("required_operations")),
            )
    arguments = {
        "level": level, 
        "theme": (baseline.preferences or {}).get("theme", ""),
        "style": (baseline.preferences or {}).get("style", ""),
        }
    if decision.action in {"increase_level", "continuation"}:
        arguments["level"] = level + 1
        if explicit_ops:
            arguments.update(operations=policy.allowed_operations, required=policy.required_operations)
    elif decision.action == "standard_level_one":
        arguments["level"] = 1
    elif decision.action == "foundation_support":
        arguments.update(
            level=1, 
            operations=("+",), 
            required=("+",), 
            overrides={
                "min_operand": 0, "max_operand": FOUNDATION_MAX_VALUE, 
                "min_operations": 1, "max_operations": 1,
                "min_intermediate_value": 0, "max_intermediate_value": FOUNDATION_MAX_VALUE,
                "min_final_value": 0, "max_final_value": FOUNDATION_MAX_VALUE,
                }
                )
    elif decision.action == "focus_operator":
        maximum = max(2, min(policy.max_operand, decision.upper_bound // 2))
        arguments.update(
            operations=(decision.operation,), 
            required=(decision.operation,), 
            overrides={
                "min_operand": 0, "max_operand": maximum, 
                "min_operations": 1, "max_operations": 1,
                "min_intermediate_value": 0, "max_intermediate_value": maximum * maximum,
                "min_final_value": 0, "max_final_value": maximum * maximum,
                },
                )
    elif decision.action == "reduce_range":
        maximum = max(policy.min_operand, policy.max_operand // 2)
        arguments.update(
            operations=policy.allowed_operations, 
            required=policy.required_operations,
            overrides={name: getattr(policy, name) for name in NUMERIC_FIELDS} | {"max_operand": maximum},
            )
    else:
        return None
    
    request = compile_target(base, **arguments)
    if request.intent != "generate_problem" or request.constraints == policy:
        return None
    from coach.calculations import select_calculation
    try:
        select_calculation(
            request.constraints, 
            rng=random.Random(0), 
            max_attempts=300,
            preferred_operations=practice_preset(request.difficulty).preferred_operations,
            )
    except GenerationExhausted:
        return None
    selection = dict(metadata, explicit_operations=explicit_ops)
    return replace(request, diagnostics=request.diagnostics | {"selection": selection})


def resolve_request(request, baseline, base):
    """Apply explicit structured overrides to a previously agreed practice baseline."""
    from ai.schemas import ProblemRequest, RequestInterpretation
    fields = dict(request.diagnostics["interpreted"])
    fields["inherit_previous"] = True
    return compile_decision(
        RequestInterpretation(
            intent="generate_problem", 
            reason="none", 
            problem_request=ProblemRequest.model_validate(fields)),
        base, 
        previous_request={"difficulty": baseline.difficulty, "preferences": baseline.preferences},
        )

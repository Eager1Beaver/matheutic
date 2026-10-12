"""Ground explicit arithmetic requirements in the learner's message."""
from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache
from types import SimpleNamespace

from coach.answers import NUMBER_WORDS, parse_answer
from core.constraints import SUPPORTED_OPERATIONS
from core.expression import ExpressionError, analyze_expression, expression_structure
from core.problem_validator import ValidationIssue

from .errors import RequestInterpretationInvalid, UnsupportedProblemRequest

NUMERIC_FIELDS = (
    "min_operand", "max_operand", "min_operations", "max_operations",
    "max_intermediate_value", "max_final_value",
    )

_WORDS = "|".join(sorted(NUMBER_WORDS - {"minus", "negative"}, key=len, reverse=True))
_NUMBER = rf"(?:[0-9]+|(?:{_WORDS})(?:[ -]+(?:{_WORDS}|and))*)"
_SUBJECT = re.compile(r"intermediate(?:\s+(?:results?|values?))?|final(?:\s+(?:answers?|results?|values?))?"
                      r"|answers?|results?|operands?|numbers?|operations?|steps?", re.I)
_COMPARISON = re.compile(
    rf"(?P<comparison>strictly below|less than|smaller than|fewer than|below|under|no more than"
    rf"|not exceed|never exceed|at most|up to|at least|greater than|larger than|bigger than|more than"
    rf"|above|<=|>=|<|>)\s*(?P<number>{_NUMBER})\b", re.I
    )
_RANGE = re.compile(rf"(?:from|between)\s+(?P<low>{_NUMBER})\s+(?:to|and)\s+(?P<high>{_NUMBER})\b", re.I)
_COUNT = re.compile(rf"\b(?P<number>{_NUMBER})[- ](?:arithmetic[- ])?(?:operations?|steps?)\b", re.I)
_EXPRESSION = re.compile(r"(?<![\w.])[ (]*[0-9][0-9\s()+*/^.-]*")
_WORD_CALCULATION = re.compile(r"\b([0-9]+)\s+(plus|minus|times|multiplied by|divided by)\s+([0-9]+)\b", re.I)
_WORD_OPERATORS = {"plus": "+", "minus": "-", "times": "*", "multiplied by": "*", "divided by": "/"}
_FIXED = re.compile(r"\busing\s+exactly\s+([^.;!?]+)", re.I)
_RELATIVE = re.compile(r"\b(?:another|same (?:kind|type|difficulty|requirements|as)|harder|easier|instead|this time)\b", re.I)
_NAMED_OPERATIONS = {"addition": "+", "subtraction": "-", "multiplication": "*", "division": "/"}
_NAMED_OPERATION = re.compile(r"\b(?:addition|subtraction|multiplication|division)\b", re.I)


def _invalid(code: str, message: str) -> RequestInterpretationInvalid:
    return RequestInterpretationInvalid([ValidationIssue(code, message)])


def _integer(text: str) -> int | None:
    value = parse_answer(text.strip().removesuffix(" and"))
    return value.numerator if value is not None and value.denominator == 1 and value >= 0 else None


def _field(text: str, start: int, end: int, *, lower: bool) -> str | None:
    suffix = re.match(r"\s*(operations?|steps?)\b", text[end:], re.I)
    subjects = list(_SUBJECT.finditer(text[:start]))
    subject = suffix.group(1).lower() if suffix else (subjects[-1].group().lower() if subjects else "")
    if subject.startswith(("operation", "step")):
        return "min_operations" if lower else "max_operations"
    if subject.startswith(("final", "answer")):
        return None if lower else "max_final_value"
    if subject.startswith(("intermediate", "result")):
        return None if lower else "max_intermediate_value"
    if subject.startswith(("number", "operand")):
        return "min_operand" if lower else "max_operand"
    return None


def explicit_limits(text: str) -> dict[str, int]:
    """Read supported range, comparison, and exact operation-count phrases."""
    limits = {}

    def add(field: str | None, value: int | None) -> None:
        if field is None or value is None:
            return
        if field in limits:
            value = max(value, limits[field]) if field.startswith("min_") else min(value, limits[field])
        limits[field] = value

    for match in _RANGE.finditer(text):
        add(_field(text, match.start(), match.end(), lower=True), _integer(match.group("low")))
        add(_field(text, match.start(), match.end(), lower=False), _integer(match.group("high")))
    for match in _COMPARISON.finditer(text):
        comparison = match.group("comparison").lower()
        exclusive_lower = comparison in {"greater than", "larger than", "bigger than", "more than", "above", ">"}
        lower = comparison in {"at least", ">="} or exclusive_lower
        negated_above = exclusive_lower and re.search(
            r"\bno\s+(?:numbers?|operands?|intermediate results?|final results?)\s*$", text[:match.start()], re.I)
        if negated_above:
            lower = False
        value = _integer(match.group("number"))
        if value is not None:
            if comparison in {"strictly below", "less than", "smaller than", "fewer than", "below", "under", "<"}:
                value -= 1
            elif exclusive_lower and not negated_above:
                value += 1
        add(_field(text, match.start(), match.end(), lower=lower), value)
    for match in _COUNT.finditer(text):
        prefix = text[max(0, match.start() - 25):match.start()]
        if re.search(r"(?:at least|at most|from|between|to|and|below|above|than|up to)\s*$", prefix, re.I):
            continue
        value = _integer(match.group("number"))
        add("min_operations", value)
        add("max_operations", value)
    return limits


def explicit_expression(text: str) -> str | None:
    """Extract an unambiguous literal calculation without evaluating learner answers."""
    expressions = []
    for match in _WORD_CALCULATION.finditer(text):
        expressions.append(f"{match.group(1)} {_WORD_OPERATORS[match.group(2).lower()]} {match.group(3)}")
    for match in _EXPRESSION.finditer(text):
        expression = match.group().strip().rstrip(".").strip()
        if not any(operator in expression for operator in "+-*/^"):
            continue
        try:
            analyze_expression(expression)
        except ExpressionError as error:
            raise UnsupportedProblemRequest(
                "The requested expression is outside the supported arithmetic domain.",
                reason="impossible_constraints" if error.code == "division_by_zero" else "unsupported_math",
            ) from error
        expressions.append(expression)
    if not expressions:
        return None
    signatures = {expression_structure(expression) for expression in expressions}
    if len(signatures) != 1:
        raise _invalid("ambiguous_requested_expression", "The request contains several different calculations.")
    return expressions[0]


def _fixed_operands(text: str) -> list[int] | None:
    match = _FIXED.search(text)
    if match is None:
        return None
    tokens = list(re.finditer(r"[a-z]+|[0-9]+|[^\w\s]", match.group(1), re.I))
    end = 0
    for token in tokens:
        if token.group().lower() not in NUMBER_WORDS | {"and", ",", "-"} and not token.group().isdigit():
            break
        end = token.end()
    phrase = match.group(1)[:end].strip().rstrip(",").removesuffix(" and")
    parts = re.split(r"\s*,\s*(?:and\s+)?", phrase)
    numbers = [_integer(part) for part in parts]
    if len(numbers) >= 2 and all(value is not None for value in numbers):
        return numbers
    if len(parts) > 1:
        raise _invalid("ambiguous_fixed_quantities", "Use digits or commas to identify the fixed quantities clearly.")
    if _integer(phrase) is not None:
        return None
    words = re.split(r"\s+and\s+", phrase)
    if all(word.isdigit() for word in words):
        return [int(word) for word in words] if len(words) >= 2 else None
    if len(words) > 128:
        raise _invalid("ambiguous_fixed_quantities", "Use a shorter list of fixed quantities.")

    @lru_cache(maxsize=None)
    def alternatives(start: int) -> tuple[tuple[int, ...], ...]:
        if start == len(words):
            return ((),)
        found = []
        for end in range(start + 1, len(words) + 1):
            phrase = " and ".join(words[start:end])
            if len(phrase) > 160:
                break
            value = _integer(phrase)
            if value is None:
                continue
            for tail in alternatives(end):
                if len(tail) < 32:
                    found.append((value,) + tail)
                    if len(found) == 2:
                        return tuple(found)
        return tuple(found)

    choices = [choice for choice in alternatives(0) if len(choice) >= 2]
    if len(choices) > 1:
        raise _invalid("ambiguous_fixed_quantities", "Use digits or commas to identify the fixed quantities clearly.")
    return list(choices[0]) if choices else None


def ground_request(spec, text: str, previous: dict | None = None) -> tuple[SimpleNamespace, dict]:
    """Resolve defaults and source-supported numeric requirements for one exercise."""
    fields = spec.model_dump() if hasattr(spec, "model_dump") else vars(spec).copy()
    original = fields.copy()
    inherited = previous.get("constraints", {}) if previous and _RELATIVE.search(text) else {}
    limits = explicit_limits(text)
    for evidence in fields.get("constraint_evidence", []):
        field = evidence["field"] if isinstance(evidence, dict) else evidence.field
        quote = evidence["quote"] if isinstance(evidence, dict) else evidence.quote
        if not re.search(r"(?<!\w)" + re.escape(quote.strip()) + r"(?!\w)", text, re.I):
            raise _invalid("unquoted_constraint", "Constraint evidence is absent from the learner message.")
        quoted_limits = explicit_limits(quote)
        if field not in quoted_limits:
            raise _invalid("unverified_constraint", "The quoted text does not establish the claimed numeric constraint.")
        if field not in limits:
            limits[field] = quoted_limits[field]
    for field in NUMERIC_FIELDS:
        fields[field] = limits.get(field, inherited.get(field))
    for match in re.finditer(r"\b(?:no|without|remove)\s+(intermediate|final|result)\s+(?:limits?|caps?)\b", text, re.I):
        targets = ("max_intermediate_value", "max_final_value") if match.group(1).lower() == "result" else (
            "max_intermediate_value" if match.group(1).lower() == "intermediate" else "max_final_value",)
        for field in targets:
            if field in limits:
                raise UnsupportedProblemRequest(reason="impossible_constraints")
            fields[field] = None

    expression = explicit_expression(text)
    supplied_expression = fields.get("required_expression")
    if supplied_expression is not None and expression is None:
        raise _invalid("unquoted_expression", "The requested expression cannot be grounded in the learner message.")
    fields["required_expression"] = expression
    fixed = _fixed_operands(text)
    if expression is not None:
        analysis = analyze_expression(expression)
        if fixed is not None and Counter(fixed) != Counter(analysis.operands):
            raise UnsupportedProblemRequest(reason="impossible_constraints")
        fixed = list(analysis.operands)
        count = len(analysis.operations)
        if ((limits.get("min_operations") is not None and count < limits["min_operations"])
                or (limits.get("max_operations") is not None and count > limits["max_operations"])):
            raise UnsupportedProblemRequest(reason="impossible_constraints")
        fields["min_operations"] = fields["max_operations"] = count
        actual = set(analysis.operations)
        named = set()
        forbidden = set()
        for match in _NAMED_OPERATION.finditer(text):
            operator = _NAMED_OPERATIONS[match.group().lower()]
            if re.search(r"\b(?:without|no|forbid)\s+(?:using\s+)?$", text[:match.start()], re.I):
                forbidden.add(operator)
            else:
                named.add(operator)
        if actual & forbidden:
            raise UnsupportedProblemRequest(reason="impossible_constraints")
        if named:
            if re.search(r"\bor\b", text, re.I):
                conflicting = not actual <= named
            else:
                conflicting = not named <= actual
            if re.search(r"\bonly\s+(?:use\s+)?(?:addition|subtraction|multiplication|division)", text, re.I):
                conflicting = conflicting or not actual <= named
            if conflicting:
                raise UnsupportedProblemRequest(reason="impossible_constraints")
        fields["allowed_operations"] = [op for op in SUPPORTED_OPERATIONS if op in actual]
        fields["required_operations"] = [op for op in SUPPORTED_OPERATIONS if op in actual]
    elif fixed is None and fields.get("fixed_operands") is not None:
        supplied = fields["fixed_operands"]
        available = Counter(int(match.group()) for match in re.finditer(r"\b[0-9]+\b", text))
        if not Counter(supplied) <= available:
            raise _invalid("unquoted_fixed_operands", "Fixed quantities are absent from the learner message.")
        fixed = supplied
    fields["fixed_operands"] = fixed
    fields.setdefault("constraint_evidence", [])
    diagnostics = {"interpreted": original,
                   "grounded": {field: fields[field] for field in NUMERIC_FIELDS}
                               | {"required_expression": expression, "fixed_operands": fixed},
                   "corrected_fields": [field for field in fields if fields[field] != original.get(field)]}
    return SimpleNamespace(**fields), diagnostics

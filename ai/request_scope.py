"""Recognize explicit custom calculations outside the coach request interface."""
import re


def custom_problem_request(text: str) -> bool:
    """Identify written formulas and explicit fixed-number lists without evaluating them."""
    return bool(
        re.search(r"\d(?:\s*\))*\s*[+*/×÷]\s*(?:\(\s*)*\d", text)
        or re.search(r"\brepresented\s+by\b", text, re.I)
        or re.search(r"\b(?:using|use)\s+exactly\s+\d+\s*(?:,|and)\s*\d+", text, re.I)
        or re.fullmatch(r"\s*\d+\s*-\s*\d+\s*[?.]?\s*", text)
        )

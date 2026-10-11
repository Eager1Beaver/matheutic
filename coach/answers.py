"""Parse unambiguous English numerical answers using exact arithmetic."""
from __future__ import annotations

import re
from fractions import Fraction

# TODO: explore spacy / NLTK, 
# such hardcoded actions are not very practical on a bigger scale
# plus it complicates localization 
_SMALL = dict(zip(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(),
    range(20),
    ))
_TENS = dict(zip("twenty thirty forty fifty sixty seventy eighty ninety".split(), range(20, 100, 10)))
_SCALES = {"billion": 10**9, "million": 10**6, "thousand": 1000}
NUMBER_WORDS = frozenset(_SMALL) | frozenset(_TENS) | frozenset(_SCALES) | {"hundred", "minus", "negative"}


def _under_hundred(words: list[str]) -> int | None:
    if len(words) == 1:
        return _SMALL.get(words[0], _TENS.get(words[0]))
    if len(words) == 2 and words[0] in _TENS and words[1] in _SMALL and 1 <= _SMALL[words[1]] <= 9:
        return _TENS[words[0]] + _SMALL[words[1]]
    return None


def _under_thousand(words: list[str]) -> int | None:
    if "hundred" not in words:
        return _under_hundred(words)
    if len(words) < 2 or words[1] != "hundred" or not 1 <= _SMALL.get(words[0], 0) <= 9:
        return None
    tail = words[2:]
    if tail and tail[0] == "and":
        tail = tail[1:]
        if not tail:
            return None
    remainder = _under_hundred(tail) if tail else 0
    if remainder is None or (tail and remainder == 0):
        return None
    return _SMALL[words[0]] * 100 + remainder


def _word_number(text: str) -> int | None:
    words = text.replace("-", " ").split()
    sign = 1
    if words and words[0] in {"minus", "negative"}:
        sign = -1
        words = words[1:]
    if not words:
        return None
    value, previous_scale = 0, 10**12
    while any(word in _SCALES for word in words):
        index = next(i for i, word in enumerate(words) if word in _SCALES)
        scale = _SCALES[words[index]]
        group = _under_thousand(words[:index])
        if group is None or group == 0 or scale >= previous_scale:
            return None
        value += group * scale
        previous_scale = scale
        words = words[index + 1:]
        if words and words[0] == "and":
            words = words[1:]
            if not words:
                return None
    remainder = _under_thousand(words) if words else 0
    return None if remainder is None else sign * (value + remainder)


def parse_answer(text: str) -> Fraction | None:
    """Accept a whole numerical answer or a small set of explicit answer phrases."""
    if not isinstance(text, str) or len(text) > 160:
        return None
    text = text.strip().lower().rstrip("?!.").strip()
    text = re.sub(r"^(?:i think(?: it(?:'s| is))?|(?:my |the )?(?:final )?answer is|it(?:'s| is))\s+", "", text)
    text = text.rstrip("?!.").strip()
    if re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?", text):
        return Fraction(text)
    number = _word_number(text)
    return Fraction(number) if number is not None else None


def explicit_final_answer(text: str) -> bool:
    """Whether the learner explicitly labels a reply as the final answer."""
    return bool(re.match(r"\s*(?:(?:my|the)\s+)?final answer\s+is\b", text, re.I))

"""Small source checks for explicit operation counts and unsupported ranges."""
import re

_COUNTS = {
    name: index for index, name in enumerate(
        ("one", "two", "three", "four", "five", 
         "six", "seven", "eight", "nine", "ten",
         "eleven", "twelve", "thirteen", "fourteen", "fifteen"), 
         1,
         )
         } | {"single": 1}
_COUNT = re.compile(r"\b(\d+|" + "|".join(_COUNTS) + r")[ -]+(?:operations?|steps?)\b", re.I)
_RANGE = re.compile(
    r"\b(?:operands?|numbers?|intermediate(?: results?| values?)?|final(?: answers?| results?| values?)?|answers?)"
    r"[^\d.!?]{0,35}(\d+)\s*(?:\.\.|to|through|[-–])\s*(\d+)\b", re.I)


def exact_operation_count(text: str) -> int | None:
    """Extract a single unqualified exact operation count without guessing ranges."""
    counts = set()
    for match in _COUNT.finditer(text):
        prefix = text[:match.start()].lower().rstrip()
        suffix = text[match.end():].lower().lstrip()
        if re.search(r"(?:at (?:least|most)|up to|(?:no )?(?:more|less|fewer) than|maximum(?: of)?|minimum(?: of)?|or|and|to)\s*$", prefix):
            continue
        if re.match(r"(?:maximum|minimum|max|min|at most|at least)\b", suffix):
            continue
        token = match.group(1).lower()
        counts.add(int(token) if token.isdigit() else _COUNTS[token])
    return next(iter(counts)) if len(counts) == 1 else None


def source_request_issue(text: str) -> str | None:
    """Identify explicitly reversed practice ranges or fresh numbered levels above five."""
    if any(int(match.group(1)) > int(match.group(2)) for match in _RANGE.finditer(text)):
        return "impossible_constraints"
    numbered = re.search(r"\b(?:difficulty(?:\s+level)?|level)\s*(\d+)\b", text, re.I)
    if numbered and not 1 <= int(numbered.group(1)) <= 5:
        return "unsupported_difficulty"
    return None

"""RULE 702.96: the alternative rules text used by an overloaded spell."""
from copy import copy
import re

from ..normalize import strip_reminder_text


OVERLOAD_LINE_RE = re.compile(r"^overload\s+(?P<cost>(?:\{[^}]+\})+)\.?$", re.I)
_TARGET = re.compile(r"\btarget\b", re.I)


def variant(card):
    """Return a parser view without the Overload instruction, with the cast text."""
    lines = strip_reminder_text(getattr(card, "oracle_text", "") or "").splitlines()
    for i, line in enumerate(lines):
        match = OVERLOAD_LINE_RE.fullmatch(line.strip())
        if match:
            overloaded = copy(card)
            overloaded.overload_payment = match["cost"]
            overloaded.oracle_text = "\n".join(
                _TARGET.sub(lambda word: "Each" if word[0][0].isupper() else "each", text)
                for index, text in enumerate(lines) if index != i
            )
            overloaded.keywords = [word for word in card.keywords if word.lower() != "overload"]
            return overloaded
    return None

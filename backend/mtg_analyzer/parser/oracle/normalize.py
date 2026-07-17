"""Step 1 of the front-end pipeline: normalize oracle text (docs/09).

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md ("THE FRONT-END PIPELINE",
step 1 NORMALIZE). Turns a card's printed rules text into a canonical form
the segmenter and handler regexes can match against without each pattern
having to re-handle reminder text, capitalisation, spelled-out numbers, or
the card referring to itself by name.

Pure text→text; **no `game/` imports** (the front-end is the security
boundary — docs/09). Deliberately conservative: it only folds forms that are
unambiguous, so a handler that fails to match falls through to the coverage
gate rather than matching a mis-normalized string.
"""

from __future__ import annotations

import re
from typing import Optional

#: Reminder text is always fully parenthesised (RULE 207.2) and never nests, so
#: repeatedly peeling the innermost parens removes it without a real grammar.
_REMINDER = re.compile(r"\s*\([^()]*\)")

#: Spelled-out small numbers → digits. Capped at twelve — larger counts are
#: printed as digits on real cards, and "a"/"an" stay words (a handler that
#: wants "a card" == "1 card" folds that itself, so we don't corrupt the many
#: non-numeric "a"/"an" occurrences here).
_NUMBER_WORDS: dict[str, str] = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12",
}
_NUMBER_WORD_RE = re.compile(
    r"\b(" + "|".join(_NUMBER_WORDS) + r")\b", re.IGNORECASE
)

#: The self-reference placeholder a card's own name folds to, so one handler
#: matches every card ("~ deals 3 damage" regardless of the printed name).
SELF = "~"


def strip_reminder_text(text: str) -> str:
    """Remove all parenthesised reminder text (RULE 207.2), innermost-first."""
    prev = None
    while prev != text:
        prev = text
        text = _REMINDER.sub("", text)
    return text


def _fold_self_name(text: str, name: Optional[str]) -> str:
    """Replace the card's own name (and its short/front-face form) with `SELF`.

    A card refers to itself by full name in oracle text; folding it to ``~``
    (the same token real cards use) lets one handler match any card. The
    front face before a comma or ``//`` is also folded, since cards self-refer
    by first name ("Nissa" for "Nissa, Who Shakes the World").
    """
    if not name:
        return text
    forms = {name}
    forms.add(name.split("//")[0].strip())
    forms.add(name.split(",")[0].strip())
    for form in sorted(forms, key=len, reverse=True):  # longest first
        if form:
            text = re.sub(r"\b" + re.escape(form) + r"\b", SELF, text)
    return text


def normalize(text: str, name: Optional[str] = None) -> str:
    """Canonicalise ``text`` for the segmenter and handler table (docs/09).

    Strips reminder text, folds the card's own ``name`` to ``~``, lowercases,
    folds spelled-out numbers to digits, and collapses runs of spaces/tabs —
    while **preserving newlines**, which separate a card's distinct abilities
    and drive segmentation.
    """
    text = strip_reminder_text(text or "")
    text = _fold_self_name(text, name)
    text = text.lower()
    text = _NUMBER_WORD_RE.sub(lambda m: _NUMBER_WORDS[m.group(1).lower()], text)
    # Collapse horizontal whitespace only; keep '\n' as the ability separator.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()

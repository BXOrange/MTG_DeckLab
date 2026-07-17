"""Saga chapter-line grammar (RULE 714) — pure roman-numeral parsing.

A Saga's chapter abilities are printed as ``"<numerals> — <effect>"`` lines
(e.g. ``"I, II — Create a 2/2 white Knight creature token."``), not the usual
"When/Whenever/At" trigger wrapper `segmenter.py` otherwise recognises. This
module is the shared, pure (no `game/` imports) home for that numeral
grammar, used by both:

* `segmenter.segment_line` — turns one chapter line into a ``triggered``
  `AbilitySpec` (``trigger={"event": "SAGA_CHAPTER", "chapter": [...]}``);
* `game/rules_engine.py`'s ``_saga_final_chapter`` — the highest chapter
  number across the whole card, driving the RULE 704.5x sacrifice check.

Text reaching this module has already been through `normalize()`, so it's
lowercased — the numerals are matched as lowercase letters.
"""

from __future__ import annotations

import re
from typing import Optional

#: Roman-numeral chapter markers Sagas print, lowercase (post-`normalize`).
_ROMAN: dict[str, int] = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7}

#: A whole chapter line: one or more comma-separated numerals, an em/en/hyphen
#: dash, then the effect body ("i, ii — create a 2/2 white knight...").
CHAPTER_LINE_RE = re.compile(
    r"^(?P<chapters>[ivx]+(?:\s*,\s*[ivx]+)*)\s*[—–-]\s*(?P<body>.+)$", re.S
)


def parse_chapter_token(token: str) -> Optional[list[int]]:
    """``"i, ii"`` → ``[1, 2]``, or ``None`` if any part isn't a known numeral."""
    numbers: list[int] = []
    for part in re.split(r"\s*,\s*", token.strip()):
        value = _ROMAN.get(part)
        if value is None:
            return None
        numbers.append(value)
    return numbers or None


def all_chapter_numbers(oracle_text: str) -> list[int]:
    """Every chapter number named by a chapter-line in ``oracle_text``.

    Text-based and line-by-line (not normalised first — this reads the raw
    printed text directly), so `_saga_final_chapter` can find the last
    chapter without depending on the full parse pipeline. Case-insensitive so
    it works on either raw (uppercase "I —") or normalised (lowercase) text.
    """
    numbers: list[int] = []
    for raw_line in (oracle_text or "").split("\n"):
        match = CHAPTER_LINE_RE.match(raw_line.strip().lower())
        if match is not None:
            parsed = parse_chapter_token(match.group("chapters"))
            if parsed:
                numbers.extend(parsed)
    return numbers

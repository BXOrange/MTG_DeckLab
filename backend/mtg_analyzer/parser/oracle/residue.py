"""PAR-175 M5: the minimal unclaimed span of a line the gate could not claim.

The gate is all-or-nothing (docs/09), so an unclaimed line blocks its whole card and
`ParseResult.unclaimed` carries the whole line. That is the right *verdict* but a poor
*work list*: a long line whose last sentence is the only gap ranks as a one-of-a-kind template.
This module narrows a failed line to the one sentence or connector part ("..., then X") whose
removal lets the rest be claimed. The result is **report data only** (`ParseResult.unclaimed_spans`):
the line stays unclaimed and the card stays `UNMODELED`, so no clause is ever dropped from a
`MODELED` card (docs/concepts/14 S4: residue-aware sequencing is a report, not a repair).

Pure -- no `game/` imports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

#: A part separator: a sentence end ("Draw a card. Discard a card.") or a "then" connector
#: ("..., then X", "; then X"). Quotes and parentheses protect their inside (a granted ability
#: has its own sentences).
_SENTENCE_END_RE = re.compile(r'(?:(?<=\.)|(?<=\."))\ +')
_THEN_CONNECTOR_RE = re.compile(r"(?:, then |; then )")
#: Lines that open with a trigger/condition/cost head: that first part names *when*, so it can
#: never be the part that is "extra" (dropping it leaves a headless body, which is a different line).
_HEAD_RE = re.compile(r"(?:when|whenever|at the|if|as long|\{|[^.:]*:)", re.I)
#: A line with more parts than this is not probed (each probe is a parse; the longest printed
#: ability lines have a handful of sentences).
MAX_PROBED_PARTS = 8


@dataclass(frozen=True)
class UnclaimedSpan:
    """One unclaimed ``line`` and the minimal ``span`` of it that blocked the claim.

    ``span == line`` when no single part could be isolated (a one-part line, a fully
    unclaimed line, or several bad parts).
    """

    line: str
    span: str


def _protected_mask(text: str) -> list[bool]:
    """True for characters inside a quotation or parenthesis (never a part boundary)."""
    mask = [False] * len(text)
    in_quote = False
    depth = 0
    for i, ch in enumerate(text):
        if ch == '"':
            in_quote = not in_quote
        elif ch == "(":
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
        mask[i] = in_quote or depth > 0
    return mask


def split_parts(line: str) -> list[tuple[str, str]]:
    """Split ``line`` into ``(separator_before, text)`` parts at sentence ends and "then" connectors."""
    mask = _protected_mask(line)
    cuts: list[tuple[int, int]] = []
    for pattern in (_SENTENCE_END_RE, _THEN_CONNECTOR_RE):
        for m in pattern.finditer(line):
            if not mask[m.start()]:
                cuts.append((m.start(), m.end()))
    cuts.sort()
    parts: list[tuple[str, str]] = []
    pos = 0
    sep = ""
    for start, end in cuts:
        if start < pos:
            continue
        parts.append((sep, line[pos:start]))
        sep = line[start:end]
        pos = end
    parts.append((sep, line[pos:]))
    return [(s, t) for s, t in parts if t.strip()]


def _without(parts: list[tuple[str, str]], drop: int, ends_with_period: bool) -> str:
    kept = [(s, t) for i, (s, t) in enumerate(parts) if i != drop]
    text = "".join((s if k else "") + t for k, (s, t) in enumerate(kept))
    if ends_with_period and not text.endswith("."):
        text += "."
    return text


def minimal_unclaimed_span(line: str, claims: Callable[[str], bool]) -> str:
    """The one part of ``line`` whose removal makes ``claims`` accept the rest, else ``line``.

    ``claims(text)`` answers whether the gate's segmenter claims ``text`` as a line. Exactly one
    isolating part is required: zero (everything is bad, or the parts only work together) and more
    than one (the parts are not independent) both fall back to the whole line.
    """
    parts = split_parts(line)
    if len(parts) < 2 or len(parts) > MAX_PROBED_PARTS:
        return line
    has_head = _HEAD_RE.match(line) is not None
    ends_with_period = line.rstrip().endswith(".")
    found: Optional[str] = None
    for index, (_sep, text) in enumerate(parts):
        if index == 0 and has_head:
            continue
        rest = _without(parts, index, ends_with_period)
        try:
            ok = claims(rest)
        except Exception:  # a probe that crashes is just "not claimed"
            ok = False
        if ok:
            if found is not None:
                return line
            found = text.strip()
    return found if found is not None else line

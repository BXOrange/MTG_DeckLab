"""Leveler (RULE 711) / Class (RULE 716) block grammar — pure text splitting.

Both card types print a multi-line **block** structure the rest of the
front-end pipeline doesn't otherwise meet: a header line, then one or more
body lines that only apply while the object's own level/class-level counter
satisfies that block's range. This module is the shared, pure (no `game/`
imports) home for recognising the header lines and splitting a card's
(already-normalised) oracle text into a preamble plus its blocks — the
line-by-line handlers (`segmenter.segment_line`, `static_effect_specs`, …)
still own parsing each *body* line; this only owns the block shape:

* Leveler (RULE 711.4c): ``"LEVEL n-m"`` / ``"LEVEL n+"``, then a bare P/T
  line, then 0+ ability lines — tiers are mutually exclusive.
* Class (RULE 716.3): ``"<cost>: Level n"`` (the cost precedes "Level n" on
  the header line — confirmed against real Scryfall oracle text, e.g.
  Cleric Class's ``"{3}{W}: Level 2"``), then 0+ ability lines that stay
  active for the rest of the game once that level is reached (cumulative).

Text reaching the ``split_*`` functions has already been through
`normalize()` (lowercased); `leveler_base_text` instead reads a card's raw
``oracle_text`` directly (mirroring `parse_keywords`'s own raw-text
cross-checks), so its header regex is case-insensitive.
"""

from __future__ import annotations

import re
from typing import Optional

#: A Leveler tier header, its own line: "level 2-6" / "level 7+".
LEVEL_TIER_RE = re.compile(
    r"^level\s+(?P<lo>\d+)\s*(?:[-–—]\s*(?P<hi>\d+)|(?P<plus>\+))\s*$"
)

#: A bare P/T line inside a Leveler tier block: "2/2" or "*/*".
PT_LINE_RE = re.compile(r"^(?P<power>\d+|\*)/(?P<toughness>\d+|\*)\s*$")

#: A Class level header: "{1}{g}: level 2" — the cost precedes "level n" on
#: the header line (verified against real Scryfall oracle text; a Class
#: level header is templated cost-first, the reverse of what an earlier
#: version of this regex assumed — see the module docstring). Checked
#: before the generic ``<cost>: <effect>`` activated-ability grammar since
#: this shape's "effect" (becoming that level) isn't on the header line
#: itself.
CLASS_LEVEL_RE = re.compile(r"^(?P<cost>.+?)\s*:\s*level\s+(?P<n>\d+)\s*$")

#: A Leveler's own "Level up {cost}" line (RULE 711.4a). "Level Up" is
#: already a registered RULE 702.87 keyword (a COST shape, like Kicker), so
#: the generic keyword catalogue harmlessly claims this line as a bare
#: keyword — but nothing consumes a COST-shape keyword into behaviour (the
#: same "parameter binds but nothing acts on it yet" gap as Kicker/Escape).
#: This is the actual mechanic: recognised here, not as an ordinary
#: ``<cost>: <effect>`` line, since it has no colon.
LEVEL_UP_LINE_RE = re.compile(r"^level up\s+(?P<cost>\{.+\})\s*$")

#: Case-insensitive version of `LEVEL_TIER_RE`, for scanning raw oracle text.
_LEVEL_TIER_RE_RAW = re.compile(LEVEL_TIER_RE.pattern, re.IGNORECASE)


def split_leveler_blocks(
    text: str,
) -> tuple[list[str], list[tuple[int, Optional[int], list[str]]]]:
    """Split normalised Leveler text into a preamble + its ``LEVEL`` blocks.

    Returns ``(preamble_lines, blocks)`` where each block is
    ``(lo, hi_or_None, body_lines)`` — ``hi`` is ``None`` for a "n+" tier.
    """
    lines = [line for line in text.split("\n") if line.strip()]
    preamble: list[str] = []
    blocks: list[tuple[int, Optional[int], list[str]]] = []
    current: Optional[tuple[int, Optional[int], list[str]]] = None

    for line in lines:
        match = LEVEL_TIER_RE.match(line.strip())
        if match is not None:
            if current is not None:
                blocks.append(current)
            lo = int(match.group("lo"))
            hi = None if match.group("plus") else int(match.group("hi"))
            current = (lo, hi, [])
        elif current is not None:
            current[2].append(line)
        else:
            preamble.append(line)
    if current is not None:
        blocks.append(current)
    return preamble, blocks


def split_class_blocks(text: str) -> tuple[list[str], list[tuple[int, str, list[str]]]]:
    """Split normalised Class text into a preamble + its ``<cost>: Level N`` blocks.

    Returns ``(preamble_lines, blocks)`` where each block is
    ``(level, cost_text, body_lines)``.
    """
    lines = [line for line in text.split("\n") if line.strip()]
    preamble: list[str] = []
    blocks: list[tuple[int, str, list[str]]] = []
    current: Optional[tuple[int, str, list[str]]] = None

    for line in lines:
        match = CLASS_LEVEL_RE.match(line.strip())
        if match is not None:
            if current is not None:
                blocks.append(current)
            current = (int(match.group("n")), match.group("cost").strip(), [])
        elif current is not None:
            current[2].append(line)
        else:
            preamble.append(line)
    if current is not None:
        blocks.append(current)
    return preamble, blocks


def leveler_base_text(oracle_text: str) -> str:
    """The raw-text prefix of ``oracle_text`` before its first ``LEVEL`` tier.

    Used by `catalogue.keywords.parse_keywords` to cross-check which of
    Scryfall's (position-blind) ``keywords`` array entries are actually
    unconditional (printed in the base text) versus tier-only (printed only
    inside a ``LEVEL`` block, and so must be re-granted level-gated instead —
    see the docstring there).
    """
    for raw_line in (oracle_text or "").split("\n"):
        if _LEVEL_TIER_RE_RAW.match(raw_line.strip()):
            return oracle_text.split(raw_line, 1)[0]
    return oracle_text or ""

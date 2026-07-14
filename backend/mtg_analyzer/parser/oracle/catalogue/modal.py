"""Modal spell block grammar — "Choose one —" / "Choose one or both —"
(RULE 700.2).

Mirrors `catalogue/levels.py`'s Leveler/Class block grouper: a "Choose
one —" header followed by one or more "• " mode lines is a **block**
ordinary per-line segmentation can't see across (a bullet line has no
trigger/activation/static shape of its own — it only means something as
part of the header above it). This module owns recognising and splitting
that shape; `gate.py` still drives parsing each mode's own *body* through
the existing effect-body machinery (`segmenter.parse_effect_body`).

Scryfall's number-word "Choose one —"/"Choose one or both —" folds to
"choose 1 —"/"choose 1 or both —" via `normalize.py`'s spelled-number
folding, so the header regex only needs digits. "Choose one or more —"
(e.g. Farewell) and non-bullet modal shapes ("Choose one. If you control a
commander …") aren't this grammar — left unclaimed (fail-closed), a
separate template for later work.

Pure text splitting — **no `game/` imports** (front-end security boundary).
"""

from __future__ import annotations

import re
from typing import Optional

#: A modal spell's header line (RULE 700.2). ``or_both`` captures RULE
#: 700.2e's "Choose one or both —" (the engine also offers casting both
#: modes together, in printed order).
MODAL_HEADER_RE = re.compile(r"^choose 1(?P<or_both> or both)?\s*—\s*$")

#: One mode line: "• <effect body>." (Scryfall's modal bullet).
MODE_LINE_RE = re.compile(r"^•\s*(?P<body>.+)$")


def split_modal_block(
    lines: list[str], start: int
) -> Optional[tuple[bool, list[str], int]]:
    """If ``lines[start]`` is a modal header, collect its "• " mode lines.

    Returns ``(or_both, mode_bodies, next_index)`` where ``next_index`` is
    the index of the first line after the block, or ``None`` when
    ``lines[start]`` isn't a modal header or has fewer than two mode lines
    following it (not really modal — fail-closed rather than guess).
    """
    header = MODAL_HEADER_RE.match(lines[start].strip())
    if header is None:
        return None
    bodies: list[str] = []
    i = start + 1
    while i < len(lines):
        mode = MODE_LINE_RE.match(lines[i].strip())
        if mode is None:
            break
        bodies.append(mode.group("body").strip())
        i += 1
    if len(bodies) < 2:
        return None
    return bool(header.group("or_both")), bodies, i

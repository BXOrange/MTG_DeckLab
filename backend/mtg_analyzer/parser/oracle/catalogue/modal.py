"""Modal block grammar — "Choose one —" / "Choose one or both —"
(RULE 700.2).

Mirrors `catalogue/levels.py`'s Leveler/Class block grouper: a "Choose
one —" header followed by one or more "• " mode lines is a **block**
ordinary per-line segmentation can't see across (a bullet line has no
trigger/activation/static shape of its own — it only means something as
part of the header above it). This module owns recognising and splitting
that shape; `gate.py` still drives parsing each mode's own *body* through
the existing effect-body machinery (`segmenter.parse_effect_body`), and
also drives the header's own recognition — a bare header for a modal
*spell* (`split_modal_block`), or a header preceded by a trigger wrapper
("When ~ enters, choose one —") for a modal *triggered ability* on a
permanent (`collect_mode_bodies`, called from `gate.py` after it peels the
trigger wrapper itself — this module doesn't know about trigger phrasing).

Scryfall's number-word "Choose one —"/"Choose two —"/"Choose one or
both —"/"Choose one or more —" folds to "choose 1 —"/"choose 2 —"/
"choose 1 or both —"/"choose 1 or more —" via `normalize.py`'s spelled-number
folding, so the header regex only needs digits — ``choose`` (the
"modal.py" ``AbilitySpec.modes["choose"]`` field) is that captured number,
``1`` for the ordinary case. RULE 700.2's "or more" (e.g. Farewell — a
*variable* N from ``choose`` to every mode, a different grammar axis than a
fixed N) is ``or_more``; it's mutually exclusive with ``or_both`` (RULE
700.2e's fixed exactly-2-modes "or both" pseudo-choice) — Scryfall never
prints both suffixes on the same header. Non-bullet modal shapes ("Choose
one. If you control a commander …") aren't this grammar — left unclaimed
(fail-closed), a separate template for later work.

Pure text splitting — **no `game/` imports** (front-end security boundary).
"""

from __future__ import annotations

import re
from typing import Optional

#: A modal header line (RULE 700.2), bare — a spell's own first line, or the
#: part after a trigger wrapper's comma has been peeled off by the caller.
#: ``choose`` is the mode count ("Choose two —" → ``2``, or the *minimum*
#: when ``or_more``); ``or_both`` captures RULE 700.2e's "Choose one or
#: both —" specifically (``choose`` is always ``1`` when ``or_both`` is set —
#: "choose 2 or both" isn't a real template); ``or_more`` captures "Choose
#: *N* or more —" (a variable N from ``choose`` to every mode).
MODAL_HEADER_RE = re.compile(
    r"^choose (?P<n>\d+)(?P<or_both> or both)?(?P<or_more> or more)?\s*—\s*$"
)

#: One mode line: "• <effect body>." (Scryfall's modal bullet).
MODE_LINE_RE = re.compile(r"^•\s*(?P<body>.+)$")


def collect_mode_bodies(lines: list[str], start: int) -> Optional[tuple[list[str], int]]:
    """Collect consecutive "• " mode lines starting at ``lines[start]``.

    Returns ``(mode_bodies, next_index)`` where ``next_index`` is the index
    of the first line after the block, or ``None`` when fewer than two mode
    lines are found (not really modal — fail-closed rather than guess).
    Shared by a modal spell's header (`split_modal_block`) and a modal
    triggered ability's header (`gate.py`, after peeling the trigger
    wrapper) — the bullet shape is the same either way.
    """
    bodies: list[str] = []
    i = start
    while i < len(lines):
        mode = MODE_LINE_RE.match(lines[i].strip())
        if mode is None:
            break
        bodies.append(mode.group("body").strip())
        i += 1
    if len(bodies) < 2:
        return None
    return bodies, i


def split_modal_block(
    lines: list[str], start: int
) -> Optional[tuple[bool, bool, int, list[str], int]]:
    """If ``lines[start]`` is a bare modal header, collect its mode lines.

    Returns ``(or_both, or_more, choose, mode_bodies, next_index)`` where
    ``next_index`` is the index of the first line after the block, and
    ``choose`` is the header's mode count ("Choose two —" → ``2``, or the
    minimum when ``or_more``), or ``None`` when ``lines[start]`` isn't a
    modal header, its ``choose`` exceeds the number of mode lines actually
    printed, or it has fewer than two mode lines following it.
    """
    header = MODAL_HEADER_RE.match(lines[start].strip())
    if header is None:
        return None
    collected = collect_mode_bodies(lines, start + 1)
    if collected is None:
        return None
    bodies, next_i = collected
    choose = int(header.group("n"))
    if choose < 1 or choose > len(bodies):
        return None
    return bool(header.group("or_both")), bool(header.group("or_more")), choose, bodies, next_i

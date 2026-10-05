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

RULE 702.172a **Spree** (`split_spree_block`/`SPREE_MODE_LINE_RE`) is a
related but distinct block shape, not a variant of the grammar above: its
header carries no count at all (every Spree block is "choose one or more"
by definition), and each mode line prices itself individually
("+ <cost> — <body>.") rather than sharing one printed spell cost the way
an ordinary "• " modal block's modes do — MEC-31.

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
    r"^choose (?P<n>\d+)(?P<exhausted> that hasn't been chosen this turn)?(?P<or_both> or both)?(?P<or_more> or more)?"
    r"(?:\s*—\s*|\.\s*you may choose (?:the )?same mode more than once\.?)$"
)

#: RULE 700.2 conditional choice-count suffix.  This is deliberately
#: structural only: `conditional_modal_override` reduces the recognised
#: wording to a closed IR vocabulary before the engine ever sees it.
CONDITIONAL_MODAL_HEADER_RE = re.compile(
    r"^choose (?P<n>\d+)\.\s*if (?P<condition>.+?),\s*"
    r"(?:you may )?choose (?P<choice>any number|\d+|both|\d+ or more) instead\.?$"
)


def conditional_modal_override(condition: str, choice: str) -> Optional[dict[str, object]]:
    """Return safe modal override IR for the recurring RULE 700.2 forms.

    Unknown conditions intentionally return ``None``: accepting prose here
    without an engine predicate would turn an unimplemented restriction into
    an unconditional extra mode choice.
    """
    condition = condition.strip().lower()
    condition_key: Optional[dict[str, object]] = {
        "this spell was kicked": {"kind": "kicked"},
        "it was kicked": {"kind": "kicked"},
        "this spell's additional cost was paid": {"kind": "additional_cost_paid"},
        "this spell was cast using teamwork": {"kind": "teamwork_paid"},
    }.get(condition)
    if condition_key is None:
        subtype = re.fullmatch(r"you control a ([a-z]+) as you cast this spell", condition)
        types = re.fullmatch(
            r"there are (\d+) or more card types among cards in your graveyard", condition
        )
        if condition == "you control a commander as you cast this spell":
            condition_key = {"kind": "controls_commander_as_cast"}
        elif subtype is not None:
            condition_key = {"kind": "controls_subtype_as_cast", "subtype": subtype.group(1)}
        elif types is not None:
            condition_key = {
                "kind": "card_types_in_graveyard_at_least",
                "amount": int(types.group(1)),
            }
        elif condition == "you descended this turn":
            condition_key = {"kind": "descended_this_turn"}
        elif (life := re.fullmatch(r"you have exactly (\d+) life", condition)) is not None:
            condition_key = {"kind": "life_total_exactly", "amount": int(life.group(1))}
    if condition_key is None:
        return None
    choice = choice.strip().lower()
    if choice == "any number":
        return {"condition": condition_key, "at_least": True, "choose": 1}
    if choice == "both":
        return {"condition": condition_key, "choose": 2}
    if choice.isdigit():
        return {"condition": condition_key, "choose": int(choice)}
    if choice.endswith(" or more") and choice[:-8].isdigit():
        return {"condition": condition_key, "at_least": True, "choose": int(choice[:-8])}
    return None

#: One mode line: "• <effect body>." (Scryfall's modal bullet).
MODE_LINE_RE = re.compile(r"^•\s*(?P<body>.+)$")

#: RULE 702.172a Spree's own header — "Spree (Choose one or more additional
#: costs.)" strips to a bare "spree" line once `normalize` peels its always-
#: parenthesised reminder text, the same way `"escalate {2}"` above loses
#: its own "(Pay this cost for each mode chosen beyond the first.)" tail.
#: Unlike RULE 700.2's `MODAL_HEADER_RE`, Spree's is a fixed, contentless
#: keyword line — the "choose one or more" instruction lives in the
#: reminder text that's already gone, so there's no count/or-both/or-more
#: to capture here at all; every Spree block is "choose 1 or more" by
#: definition (RULE 702.172a).
SPREE_HEADER_RE = re.compile(r"^spree\s*$")

#: One Spree mode line: "+ <cost> — <effect body>." — the same shape as
#: `MODE_LINE_RE`'s "• " bullet, but carrying its own per-mode mana cost
#: instead of a bare bullet, since Spree (unlike RULE 700.2's ordinary
#: modal block) prices *every* mode individually rather than sharing one
#: printed cost across all of them (RULE 702.172a: "the total cost to cast
#: this spell is its mana cost plus the additional cost of each mode
#: chosen").
SPREE_MODE_LINE_RE = re.compile(r"^\+\s*(?P<cost>\{[^}]+\})\s*—\s*(?P<body>.+)$")


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
) -> Optional[tuple[bool, bool, bool, Optional[dict[str, object]], int, list[str], int]]:
    """If ``lines[start]`` is a bare modal header, collect its mode lines.

    Returns ``(or_both, or_more, repeatable, override, choose, mode_bodies, next_index)`` where
    ``next_index`` is the index of the first line after the block, and
    ``choose`` is the header's mode count ("Choose two —" → ``2``, or the
    minimum when ``or_more``), or ``None`` when ``lines[start]`` isn't a
    modal header, its ``choose`` exceeds the number of mode lines actually
    printed, or it has fewer than two mode lines following it.
    """
    line = lines[start].strip()
    header = MODAL_HEADER_RE.match(line)
    conditional = CONDITIONAL_MODAL_HEADER_RE.match(line)
    if header is None and conditional is None:
        return None
    collected = collect_mode_bodies(lines, start + 1)
    if collected is None:
        return None
    bodies, next_i = collected
    choose = int((header or conditional).group("n"))
    if choose < 1 or choose > len(bodies):
        return None
    repeatable = "same mode more than once" in line.lower()
    override = (
        conditional_modal_override(conditional.group("condition"), conditional.group("choice"))
        if conditional is not None else None
    )
    if conditional is not None and override is None:
        return None
    # The return value remains deliberately small; gate.py reads this
    # parser-owned attribute from the header matcher for conditional blocks.
    return bool(header and header.group("or_both")), bool(header and header.group("or_more")), repeatable, override, choose, bodies, next_i


#: "As ~ enters, choose Khans or Dragons." — a named-option header (the Siege cycle, Struggle for
#: Project Purity). Only a block whose bullets are printed "• <option> — <ability>" is a named
#: choice; "choose odd or even" / "choose island or swamp" have no bullets and stay unclaimed.
NAMED_CHOICE_HEADER_RE = re.compile(
    r"^as (?:~|this [a-z]+) enters, choose (?P<a>[a-z][a-z' -]*?) or (?P<b>[a-z][a-z' -]*?)\.?$"
)

#: One named-choice bullet: "• khans — <ability line>".
NAMED_CHOICE_LINE_RE = re.compile(r"^•\s*(?P<label>[a-z][a-z' -]*?)\s+—\s+(?P<body>.+)$")


def split_named_choice_block(
    lines: list[str], start: int
) -> Optional[tuple[list[str], dict[str, str], int]]:
    """If ``lines[start]`` is a named-choice header, collect its labelled bullets.

    Returns ``(labels, {label: body}, next_index)``; ``None`` unless exactly the two named options
    each have one bullet (a block that names an option it never describes is not this shape).
    """
    header = NAMED_CHOICE_HEADER_RE.match(lines[start].strip())
    if header is None:
        return None
    labels = [header.group("a"), header.group("b")]
    bodies: dict[str, str] = {}
    i = start + 1
    while i < len(lines):
        bullet = NAMED_CHOICE_LINE_RE.match(lines[i].strip())
        if bullet is None:
            break
        bodies[bullet.group("label")] = bullet.group("body").strip()
        i += 1
    if sorted(bodies) != sorted(labels):
        return None
    return labels, bodies, i


def split_spree_block(
    lines: list[str], start: int
) -> Optional[tuple[list[str], list[str], int]]:
    """If ``lines[start]`` is a bare Spree header, collect its "+ <cost> —
    <body>" mode lines (RULE 702.172a).

    Returns ``(mode_costs, mode_bodies, next_index)`` — ``mode_costs``
    parallel to ``mode_bodies``, one raw mana-cost string per mode, in
    printed order — or ``None`` when ``lines[start]`` isn't a Spree header
    or it's followed by fewer than two "+ " lines (never a real printed
    shape; fail closed rather than guess).
    """
    if SPREE_HEADER_RE.match(lines[start].strip()) is None:
        return None
    costs: list[str] = []
    bodies: list[str] = []
    i = start + 1
    while i < len(lines):
        mode = SPREE_MODE_LINE_RE.match(lines[i].strip())
        if mode is None:
            break
        costs.append(mode.group("cost"))
        bodies.append(mode.group("body").strip())
        i += 1
    if len(bodies) < 2:
        return None
    return costs, bodies, i

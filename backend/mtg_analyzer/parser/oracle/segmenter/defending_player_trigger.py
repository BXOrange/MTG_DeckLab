"""PAR-315: "defending player" in the body of a combat trigger is the combat event's own "that player".

RULE 506.2 / 508.1b: the defending player is the player (or the planeswalker's / battle's controller) the attacking
creature attacks. The combat events a "whenever ~ attacks / attacks and isn't blocked / becomes blocked" head fires
(`ATTACKS`, `ATTACKER_UNBLOCKED`, `BECOMES_BLOCKED`) each stamp that player as ``defending_player_id``, which is exactly
what `targeting.trigger_player_antecedent` hands a "that player" body (PAR-208 / PAR-313). The body grammar already knows
every "that player <verb>" shape, so under such a head the two spellings are one referent: read the body as "that
player" and keep the printed text on the spec. Fail-closed where it matters: with no defending player the referent is
``None`` and the effect does nothing (RULE 506.2: nobody to defend).
"""

from __future__ import annotations

import dataclasses
import re
from typing import Optional

from .line_rows_abilities import line_triggered_ability
from .line_types import LineContext
from .segment_types import Segment
from .trigger_heads import TRIGGER_RE

#: Heads whose firing event names the attacked player: an attack declaration (also "attacks alone"), the unblocked-
#: attacker step (RULE 509.1h) and "becomes blocked". The head must be about *this* combat's attacker, never "a
#: creature an opponent controls attacks" (there the printed "you're the defending player" is a condition on the
#: reader, not the referent of "that player").
_COMBAT_HEAD_RE = re.compile(
    r"^(?:when|whenever)\s+[^,]*?\b(?:attacks?(?: alone)?(?: and isn't blocked)?|becomes blocked)\s*$", re.IGNORECASE,
)
#: "defending player" wherever the body says it; "target <X> defending player controls" then reads as the shared
#: "target <X> that player controls" kinds, which `gate._that_player_head_ok` admits under these heads.
_DEFENDING_PLAYER_RE = re.compile(r"\bdefending player\b", re.IGNORECASE)
_THAT_PLAYER = "that player"


def _rewritten_body(raw: str) -> Optional[str]:
    """``raw`` with its body's "defending player" read as "that player", or ``None`` when the line is not a combat
    trigger that names one."""
    m = TRIGGER_RE.match(raw)
    if m is None or _COMBAT_HEAD_RE.match(raw[: m.start("body") - 1].rstrip(", ")) is None:
        return None
    body = m.group("body")
    if "defending player" in m.group("cond").lower() or re.search(r"the defending player\b|each defending player\b", body):
        return None
    if _DEFENDING_PLAYER_RE.search(body) is None:
        return None
    return raw[: m.start("body")] + _DEFENDING_PLAYER_RE.sub(_THAT_PLAYER, body)


def line_defending_player_trigger(ctx: LineContext) -> Optional[Segment]:
    """Try the printed line first; only a line the ordinary trigger grammar leaves unclaimed is re-read with the
    body's "defending player" as "that player". Never changes a line that already parses."""
    original = line_triggered_ability(ctx)
    if original is not None and original.claimed:
        return original
    body = _rewritten_body(ctx.raw)
    if body is None:
        return original
    line = _rewritten_body(ctx.line) or body
    retried = line_triggered_ability(dataclasses.replace(ctx, raw=body, line=line))
    if retried is None or not retried.claimed or retried.spec is None:
        return original
    # The spec keeps the printed wording (`raw_text` is what `gate` and the status views quote).
    retried.spec.raw_text = ctx.raw
    return dataclasses.replace(retried, raw=ctx.raw)

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
from typing import Any, Optional

from ..catalogue.effect_rows.shared import DEFENDING_PLAYER_COMBAT_EVENTS, EVENT_PLAYER_EVENTS_KEY
from .line_rows_abilities import line_triggered_ability
from .line_types import LineContext
from .segment_types import Segment
from .trigger_heads import TRIGGER_RE

#: Heads whose firing event names the attacked player: an attack declaration (also "attacks alone"), the unblocked-
#: attacker step (RULE 509.1h) and "becomes blocked". The head must be about *this* combat's attacker, never "a
#: creature an opponent controls attacks" (there the printed "you're the defending player" is a condition on the
#: reader, not the referent of "that player").
_COMBAT_HEAD_RE = re.compile(
    r"^(?:when|whenever)\s+[^.]*?\b(?:attacks?(?: alone)?(?: and isn't blocked)?|becomes blocked)\s*$", re.IGNORECASE,
)
#: "defending player" wherever the body says it; "target <X> defending player controls" then reads as the shared
#: "target <X> that player controls" kinds, which `gate._that_player_head_ok` admits under these heads.
_DEFENDING_PLAYER_RE = re.compile(r"\bdefending player\b", re.IGNORECASE)
_THAT_PLAYER = "that player"
#: "defending player <verb>" as the subject of a player-scoped clause; read as "each opponent <verb>" on the retry, whose
#: ``for_each`` over the opponents is then narrowed to the one defending player (`_narrowed_to_defender`).
_DEFENDING_SUBJECT_RE = re.compile(
    r"\bdefending player (?=(?:loses|may|mills|discards|sacrifices|exiles|draws|gains|reveals|creates)\b)"
    r"|(?<=\bdamage to )defending player\b",
    re.IGNORECASE,
)
_EACH_OPPONENT = "each opponent"
#: `PLAYER_SCOPES` name for the single attacked player (`composition.ForEachEffect`).
_DEFENDING_SCOPE = "defending_player"


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
    if (retried is None or not retried.claimed or retried.spec is None
            or "'of': 'event_player'" in repr(retried.spec.effects)):
        # A count "taken as that player" over the event's own player would measure the attacker's controller.
        retried = _each_opponent_reading(ctx)
        if retried is None:
            return original
    # The spec keeps the printed wording (`raw_text` is what `gate` and the status views quote).
    retried.spec.raw_text = ctx.raw
    return dataclasses.replace(retried, raw=ctx.raw)


def _narrowed_to_defender(node: Any) -> bool:
    """Rewrite every ``for_each`` over ``each_opponent`` inside ``node`` (a spec dict tree, in place) to the single
    defending player and mark it for the event gate; ``False`` when "each_opponent" appears anywhere else (a
    ``scope`` / ``selector`` reading that would hit every opponent), so the clause stays unclaimed."""
    if isinstance(node, dict):
        over = node.get("over")
        if isinstance(over, dict) and over.get("players") == "each_opponent":
            node["over"] = {**over, "players": _DEFENDING_SCOPE}
            node[EVENT_PLAYER_EVENTS_KEY] = list(DEFENDING_PLAYER_COMBAT_EVENTS)
            return all(_narrowed_to_defender(v) for k, v in node.items() if k != "over")
        return all(_narrowed_to_defender(v) for v in node.values())
    if isinstance(node, (list, tuple)):
        return all(_narrowed_to_defender(v) for v in node)
    return node != "each_opponent"


def _each_opponent_reading(ctx: LineContext) -> Optional[Segment]:
    """The retry for a body only the "each opponent <verb>" vocabulary knows: claimed, and every opponent loop narrowed
    to the defending player. Needs a combat head (`_rewritten_body`'s) and a subject-position "defending player"."""
    m = TRIGGER_RE.match(ctx.raw)
    if m is None or _COMBAT_HEAD_RE.match(ctx.raw[: m.start("body") - 1].rstrip(", ")) is None:
        return None
    body = m.group("body")
    if _DEFENDING_SUBJECT_RE.search(body) is None or "defending player" in _DEFENDING_SUBJECT_RE.sub("", body):
        return None
    reread = ctx.raw[: m.start("body")] + _DEFENDING_SUBJECT_RE.sub(lambda m: _EACH_OPPONENT + (" " if m.group(0).endswith(" ") else ""), body)
    segment = line_triggered_ability(dataclasses.replace(ctx, raw=reread, line=reread))
    if segment is None or not segment.claimed or segment.spec is None:
        return None
    if not _narrowed_to_defender([e.params for e in segment.spec.effects]):
        return None
    return segment

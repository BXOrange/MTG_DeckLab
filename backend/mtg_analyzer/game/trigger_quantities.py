"""Quantities scoped to a trigger's own subject, captured when it triggers."""

from __future__ import annotations

from typing import Any


#: PAR-231: the defender kinds an `ATTACKERS_AT_DEFENDER` head accepts, keyed by its ``at_defender`` spec value.
DEFENDER_PLAYER = "player"
DEFENDER_PLAYER_OR_PLANESWALKER = "player_or_planeswalker"
DEFENDER_CONTROLLER_PLANESWALKER = "controller_planeswalker"


def _defender_group_ok(event: Any, state: Any, scope: str, source: Any) -> bool:
    """RULE 508.1b: does the defender this `ATTACKERS_AT_DEFENDER` group is aimed at fit the head?

    "a player" counts only attackers aimed at the player itself -- not at a planeswalker or battle that player
    controls or protects (Horn of the Mark's ruling); "a planeswalker you control" is a planeswalker whose
    controller is this ability's controller.
    """
    kind = event.get("defender_kind")
    if scope == DEFENDER_PLAYER:
        return kind == "player"
    if scope == DEFENDER_PLAYER_OR_PLANESWALKER:
        return kind in ("player", "planeswalker")
    if scope == DEFENDER_CONTROLLER_PLANESWALKER:
        return kind == "planeswalker" and event.get("defending_player_id") == getattr(source, "controller_id", None)
    return False


def matching_attackers(event: Any, context: Any, spec: dict, source: Any) -> list:
    """RULE 508.3a: select this head's attackers from the locked declaration."""
    from .combat import matches_object_filter

    state = context.state
    source_id = getattr(source, "instance_id", None)
    ids = event.get("attacker_ids") or []
    if spec.get("includes_source") and source_id not in ids:
        return []
    if spec.get("at_defender") and not _defender_group_ok(event, state, spec["at_defender"], source):
        return []
    result = []
    for iid in ids:
        obj = state.find_object(iid)
        if obj is None or (spec.get("other") and iid == source_id):
            continue
        # "Whenever one or more Demons you control attack **a player**" (Demonic Covenant) — RULE 508.1b: an attacker
        # attacking a planeswalker or battle doesn't count.
        if spec.get("defender") == "player" and (getattr(obj, "combat_defender", None) or {}).get("kind") != "player":
            continue
        # "Whenever three or more creatures attack **you**" (PAR-207): only the attackers whose defender is this
        # ability's controller as a player (a planeswalker they control is not "you", RULE 508.1b).
        if spec.get("defender") == "controller":
            defender = getattr(obj, "combat_defender", None) or {}
            if defender.get("kind") != "player" or defender.get("id") != getattr(source, "controller_id", None):
                continue
        if matches_object_filter(obj, spec.get("filter"), reference=source, state=state):
            result.append(obj)
    return result


def capture_attackers(event: Any, context: Any, spec: dict, source: Any) -> Any:
    """RULE 603.2: keep each ability's count even if attackers later leave or change.

    The event bus payload belongs to all listeners; only this pending trigger gets
    the enriched copy. Neither another listener nor another combat can overwrite it.
    """
    attackers = matching_attackers(event, context, spec, source)
    captured = event.copy_with(matching_attacker_count=len(attackers),
                               matching_attacker_ids=[obj.instance_id for obj in attackers],
                               # "where X is the greatest power among those creatures" (Shriekwood Devourer)
                               matching_attacker_greatest_power=max((obj.power or 0 for obj in attackers), default=0))
    captured.turn = event.turn
    return captured

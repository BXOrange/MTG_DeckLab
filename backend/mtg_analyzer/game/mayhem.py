"""RULE 702.187: play a card discarded this turn from its graveyard."""
from __future__ import annotations

from ..models.game.events import EventType
from ..models.game.game_object import Zone


def available(state, obj) -> bool:
    """The permission follows only this discarded graveyard incarnation."""
    if obj.zone != Zone.GRAVEYARD or (
        "mayhem" not in obj.parametric_keywords and "mayhem" not in obj.intrinsic_keywords
    ):
        return False
    return any(
        event.type == EventType.DISCARD_CARD
        and event.turn == state.internal_turn.number
        and event.get("player_id") == obj.owner_id
        and event.get("instance_id") == obj.instance_id
        and event.get("zone_incarnation") == obj.zone_incarnation
        for event in reversed(state.event_log)
    )


def permits_land(state, obj) -> bool:
    return available(state, obj) and not obj.parametric_keywords.get("mayhem", {}).get("cost")

from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: RULE 725.1: the monarch designation can be unheld; both the trigger and the resolution check it (RULE 603.4).
_NO_MONARCH = {"kind": "no_monarch"}


def _starscream_seeker_leader() -> list[AbilitySpec]:
    """Living metal (During your turn, this Vehicle is also a creature.)
    Flying, menace, haste
    Whenever Starscream deals combat damage to a player, if there is no monarch, that player becomes the monarch.
    Whenever you become the monarch, convert Starscream.

    -- MEC-137. Back face of Starscream, Power Hungry. "That player" is the damaged player (``become_monarch``'s
    new ``event_player`` selector); the intervening-if is the existing ``no_monarch`` condition.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("become_monarch", {"selector": "event_player"}, condition=_NO_MONARCH)],
            trigger={"event": EventType.DAMAGE, "condition": {"subject": "self"},
                     "filter": {"combat": True, "is_player": True}, "active_if": _NO_MONARCH},
            raw_text="whenever ~ deals combat damage to a player, if there is no monarch, that player becomes the monarch.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("transform", {})],
            trigger={"event": EventType.BECAME_MONARCH, "condition": {"subject": "you"}},
            raw_text="whenever you become the monarch, convert ~.",
        ),
    ]


register("Starscream, Seeker Leader", _starscream_seeker_leader)

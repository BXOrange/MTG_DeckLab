from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mangara_the_diplomat() -> list[AbilitySpec]:
    """Lifelink
    Whenever an opponent attacks with creatures, if two or more of those
    creatures are attacking you and/or planeswalkers you control, draw a
    card.
    Whenever an opponent casts their second spell each turn, draw a card.

    Documented simplification: "attacking you and/or planeswalkers you
    control" is modeled as "attacking you" (the `PLAYER_ATTACKED` aggregate
    names the defending player, not a planeswalker)."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.PLAYER_ATTACKED,
                "condition": {"subject": "group", "controller": "not_you"},
                "defender_is_you": True, "attackers_at_least": 2,
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "not_you"},
                "is_nth_spell_cast_this_turn": 2,
            },
        ),
    ]


register("Mangara, the Diplomat", _mangara_the_diplomat)

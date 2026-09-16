from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _burning_earth() -> list[AbilitySpec]:
    """Whenever a player taps a nonbasic land for mana, this enchantment
    deals 1 damage to that player. — Burning Earth. Manabarbs' own
    `"nonbasic"` sibling — `effect_binder._build_group_ok`'s new supertype
    filter (a live board check, since "Basic" isn't a main type
    `object_types` carries or a subtype after the em dash).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "selector": "event_player"})],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "group", "type": "land", "nonbasic": True},
            },
        )
    ]


register("Burning Earth", _burning_earth)

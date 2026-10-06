from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _papalymo_totolymo() -> list[AbilitySpec]:
    """Whenever you cast a noncreature spell, Papalymo Totolymo deals 1 damage to each opponent and you gain 1 life.
    {4}, {T}, Sacrifice Papalymo Totolymo: Each opponent who lost life this turn sacrifices a creature with the greatest power among creatures they control.

    — PLAY-ALL (Scions & Spellcraft). The trigger is the parser's. The activation is Professor Onyx's `sacrifice` edict
    (``greatest: power``) with the new ``each_opponent_who_lost_life_this_turn`` selector (event-derived `life_lost_this_turn`).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "selector": "each_opponent"}), EffectSpec("gain_life", {"amount": 1})],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"}, "spell_filter": {"without_card_type": "creature"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("sacrifice", {
                "what": "creature", "count": 1, "greatest": "power", "selector": "each_opponent_who_lost_life_this_turn",
            })],
            cost={"mana": "{4}", "taps_self": True, "sacrifice": "self"},
        ),
    ]


register("Papalymo Totolymo", _papalymo_totolymo)

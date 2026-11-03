from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _party_thrasher() -> list[AbilitySpec]:
    """Noncreature spells you cast from exile have convoke. (Each creature you tap while casting a noncreature spell from exile pays for {1} or one mana of that creature's color.)
At the beginning of your first main phase, you may discard a card. If you do, exile the top two cards of your library, then choose one of them. You may play that card this turn."""
    return [
        AbilitySpec("static", [EffectSpec("grant_help_pay_to_spells", {
            "keyword": "convoke", "exclude_card_type": "creature", "from_zone": "exile",
        })]),
        AbilitySpec("triggered", [EffectSpec("pay_cost_then", {
            "cost": "discard a card", "effects": [{"type": "impulsive_draw", "params": {
                "count": 2, "same_turn_only": True, "choose_one": True,
            }}],
        })], trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "main1"}, "phase_relation": "you"}),
    ]


register("Party Thrasher", _party_thrasher)

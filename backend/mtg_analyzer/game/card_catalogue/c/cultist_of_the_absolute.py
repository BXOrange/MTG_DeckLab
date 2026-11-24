from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _cultist_of_the_absolute() -> list[AbilitySpec]:
    'Commander creatures you own get +3/+3 and have flying, deathtouch, "Ward—Pay 3 life," and "At the beginning of your upkeep, sacrifice a creature."'
    return [AbilitySpec("static", [
        EffectSpec("anthem", {"affects": {"zone": "battlefield", "of": "any", "filter": {"card_type": "creature", "is_commander": True, "owned_by_you": True}}, "power": 3, "toughness": 3}),
        EffectSpec("grant_keyword", {"affects": {"zone": "battlefield", "of": "any", "filter": {"card_type": "creature", "is_commander": True, "owned_by_you": True}},
                                     "keywords": ["flying", "deathtouch"], "ward_cost": "Pay 3 life"}),
        EffectSpec("grant_triggered_ability", {
            "affects": {"zone": "battlefield", "of": "any", "filter": {"card_type": "creature", "is_commander": True, "owned_by_you": True}}, "trigger_event": "STEP_BEGIN",
            "filter": {"step": "upkeep"}, "phase_relation": "you",
            "grant_effects": [{"type": "sacrifice", "params": {"what": "creature", "count": 1, "selector": "controller"}}],
        }),
    ])]


register("Cultist of the Absolute", _cultist_of_the_absolute)

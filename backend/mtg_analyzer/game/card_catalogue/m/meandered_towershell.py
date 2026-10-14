from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _meandered_towershell() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature has islandwalk and "Whenever this creature attacks, exile it and Meandered Towershell. Return it to the battlefield under your control tapped and attacking at the beginning of the declare attackers step on your next turn, then return Meandered Towershell to the battlefield under its owner's control attached to that creature."
    """
    return [AbilitySpec("static", [
        EffectSpec("grant_keyword", {"affects": "attached_permanent", "keywords": ["islandwalk"]}),
        EffectSpec("grant_triggered_ability", {
            "affects": "attached_permanent", "trigger_event": "ATTACKS",
            "grant_effects": [{"type": "exile_self_and_grantor_until_attack", "params": {}}],
        }),
    ])]


register("Meandered Towershell", _meandered_towershell)

from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _jarad_golgari_lich_lord() -> list[AbilitySpec]:
    """Jarad gets +1/+1 for each creature card in your graveyard.
    {1}{B}{G}, Sacrifice another creature: Each opponent loses life equal to the sacrificed creature's power.
    Sacrifice a Swamp and a Forest: Return this card from your graveyard to your hand.

    — PLAY-ALL Step 2 (Sultai Arisen). The first two abilities are the parser's own claims, reproduced. The graveyard
    ability is Multani's `return_self_from_graveyard_to_hand`; its cost is the new paired sacrifice
    (`ActivationCost.sacrifice_also`): one Swamp and one *different* Forest, so a Swamp Forest pays for only one half.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "self", "power": 1, "toughness": 1,
                "power_count": {"zone": "graveyard", "of": "you", "filter": {"card_type": "creature"}},
                "toughness_count": {"zone": "graveyard", "of": "you", "filter": {"card_type": "creature"}},
            })],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("bind", {
                "name": "n", "amount": {"kind": "count_selector", "selector": "sacrificed_cost_power"},
                "effects": [{"type": "lose_life", "params": {"amount": "$n", "selector": "each_opponent"}}],
            })],
            cost={"text": "{1}{b}{g}, sacrifice another creature"},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("return_self_from_graveyard_to_hand", {})],
            cost={"text": "sacrifice a swamp and a forest"},
        ),
    ]


register("Jarad, Golgari Lich Lord", _jarad_golgari_lich_lord)

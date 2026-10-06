from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _demon_of_fate_s_design() -> list[AbilitySpec]:
    """Flying, trample
    Once during each of your turns, you may cast an enchantment spell by paying life equal to its mana value rather than paying its mana cost.
    {2}{B}, Sacrifice another enchantment: This creature gets +X/+0 until end of turn, where X is the sacrificed enchantment's mana value.

    — PLAY-ALL (Miracle Worker). Keywords are the catalogue's. The alternative cost is Conspiracy Unraveler's `granted_alt_cast_cost`
    widened with ``card_type``, ``pay_life_equal_mv`` and ``once_per_turn`` (a spent-this-turn stamp in
    `GameState.once_per_turn_grants_used`). The pump is Burnt Offering's `sacrificed_cost_mana_value` read as a `pump` ``dynamic_amount``.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("granted_alt_cast_cost", {"card_type": "enchantment", "pay_life_equal_mv": True, "once_per_turn": True})],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {
                "power": 0, "toughness": 0, "amount_from_count_selector_axis": "power",
                "dynamic_amount": {"kind": "count_selector", "selector": "sacrificed_cost_mana_value"},
            })],
            cost={"text": "{2}{b}, sacrifice another enchantment"},
        ),
    ]


register("Demon of Fate's Design", _demon_of_fate_s_design)

from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# mixed singletons on small new primitives
# ===========================================================================
# Engine: `_mass_wipe_objects` ``enchanted`` filter (Winds of Rath);
# `cost_reduction_for` ``reduce_if_targets`` (Killian, Ink Duelist);
# `continuous.count_selector` ``total_power_creatures_you_control`` (Volcanic
# Salvo); `DealDamageEffect` selector
# ``each_creature_and_planeswalker_opponents_control`` (Volcanic Torrent);
# binder predicate ``entering_mana_value_at_most`` (Tocasia's Welcome).


def _winds_of_rath() -> list[AbilitySpec]:
    """Destroy all creatures that aren't enchanted. They can't be
    regenerated."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy", {
                "selector": "all_creatures", "filter": {"enchanted": False},
                "can_be_regenerated": False,
            })],
        ),
    ]


register("Winds of Rath", _winds_of_rath)

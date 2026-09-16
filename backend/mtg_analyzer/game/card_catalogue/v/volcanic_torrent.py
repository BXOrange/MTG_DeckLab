from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _volcanic_torrent() -> list[AbilitySpec]:
    """Cascade
    Volcanic Torrent deals X damage to each creature and planeswalker your
    opponents control, where X is the number of spells you've cast this
    turn."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {
                "selector": "each_creature_and_planeswalker_opponents_control",
                "amount_from_count_selector": "spells_cast_this_turn",
            })],
        ),
    ]


register("Volcanic Torrent", _volcanic_torrent)

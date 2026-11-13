from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _osgir() -> list[AbilitySpec]:
    """Vigilance
{1}, Sacrifice an artifact: Target creature you control gets +2/+0 until end of turn.
{X}, {T}, Exile an artifact card with mana value X from your graveyard: Create two tokens that are copies of the exiled card. Activate only as a sorcery."""
    return [
        AbilitySpec("keyword", [], keyword={"name": "vigilance"}),
        AbilitySpec("activated", [EffectSpec("pump", {
            "power": 2, "toughness": 0, "target_kind": "creature_you_control",
        })], cost={"text": "{1}, sacrifice an artifact"}),
        AbilitySpec("activated", [EffectSpec("copy_paid_exile_twice", {})], cost={
            "mana": "{X}", "taps_self": True, "exile_from_graveyard": 1,
            "exile_from_graveyard_filter": "artifact", "exile_from_graveyard_mana_value_x": True,
            "sorcery_speed_only": True,
        }),
    ]


register("Osgir, the Reconstructor", _osgir)

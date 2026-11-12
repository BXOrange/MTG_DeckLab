from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register
from ...costs import TAP_OTHERS_X


def _heirloom_epic() -> list[AbilitySpec]:
    """{4}, {T}: Draw a card. For each mana in this ability's activation cost, you may tap an untapped creature you control rather than pay that mana. Activate only as a sorcery."""
    return [AbilitySpec("activated", [EffectSpec("draw", {"count": 1})], cost={
        "mana": "{4}", "taps_self": True, "sorcery_speed_only": True,
        "tap_others": [TAP_OTHERS_X, "creature"], "help_pay_kind": "tap_creatures_for_generic",
    })]


register("Heirloom Epic", _heirloom_epic)

from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _eidolon_of_countless_battles() -> list[AbilitySpec]:
    """Bestow {2}{W}{W}
    This creature and enchanted creature each get +1/+1 for each creature you
    control and +1/+1 for each Aura you control.

    Four `anthem` layer-7d specs: {self, attached} x {creatures, Auras}. When
    cast as a creature (not bestowed) the ``attached_permanent`` halves match
    nothing, exactly as the rules read."""
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {
                    "affects": "self", "power": 1, "toughness": 1,
                    "power_count": "creatures_you_control",
                    "toughness_count": "creatures_you_control",
                }),
                EffectSpec("anthem", {
                    "affects": "self", "power": 1, "toughness": 1,
                    "power_count": "auras_you_control", "toughness_count": "auras_you_control",
                }),
                EffectSpec("anthem", {
                    "affects": "attached_permanent", "power": 1, "toughness": 1,
                    "power_count": "creatures_you_control",
                    "toughness_count": "creatures_you_control",
                }),
                EffectSpec("anthem", {
                    "affects": "attached_permanent", "power": 1, "toughness": 1,
                    "power_count": "auras_you_control", "toughness_count": "auras_you_control",
                }),
            ],
        ),
    ]


register("Eidolon of Countless Battles", _eidolon_of_countless_battles)

from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sink_into_stupor() -> list[AbilitySpec]:
    """Return target spell or nonland permanent an opponent controls to
    its owner's hand.

    — MEC-12 (cEDH Kinnan/M-K). `ReturnToHandEffect`'s new
    ``spell_or_permanent`` flag routes through `RulesEngine.
    bounce_spell_or_permanent` (a still-on-the-stack target needs pulling
    out of `GameState.stack`, which the ordinary battlefield/zone-based
    `return_to_hand` has no way to reach) instead of the plain bounce.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_to_hand", {
                "target_kind": "spell_or_nonland_permanent_you_dont_control",
                "spell_or_permanent": True,
            })],
        ),
    ]


register("Sink into Stupor", _sink_into_stupor)
register("Sink into Stupor // Soporific Springs", _sink_into_stupor)

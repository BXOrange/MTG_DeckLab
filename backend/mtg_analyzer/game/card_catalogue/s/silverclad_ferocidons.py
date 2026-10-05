from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _silverclad_ferocidons() -> list[AbilitySpec]:
    """Enrage — Whenever this creature is dealt damage, each opponent
    sacrifices a permanent of their choice.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice", {"selector": "each_opponent", "what": "permanent"})],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
        ),
    ]


register("Silverclad Ferocidons", _silverclad_ferocidons)

from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _haywire_mite() -> list[AbilitySpec]:
    """When this creature dies, you gain 2 life.
    {G}, Sacrifice this creature: Exile target noncreature artifact or
    noncreature enchantment.

    Documented simplification: the target is modeled as ``artifact_or_
    enchantment`` — the "noncreature" narrowing isn't expressible on the
    exile target kind, so an artifact-creature / enchantment-creature is a
    legal target here where the real card forbids it."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_life", {"amount": 2})],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("exile", {"target_kind": "artifact_or_enchantment"})],
            cost={"mana": "{G}", "text": "{G}, Sacrifice ~"},
        ),
    ]


register("Haywire Mite", _haywire_mite)

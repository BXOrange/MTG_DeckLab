from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _excava_the_risen_past() -> list[AbilitySpec]:
    """Flying, haste
    Whenever Excava attacks, return up to one target artifact, creature, or
    non-Aura enchantment card with mana value 3 or less from your graveyard
    to the battlefield with a finality counter on it. It's a 1/1 Spirit
    creature with flying in addition to its other types.

    Documented simplification: the finality counter and the 1/1 Spirit
    flying type-overlay are not modeled — the card returns to the battlefield
    as-is."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_nonland_permanent", "destination": "battlefield",
                "max_mana_value": 3, "optional": True,
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Excava, the Risen Past", _excava_the_risen_past)

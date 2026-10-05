from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _daze() -> list[AbilitySpec]:
    """You may return an Island you control to its owner's hand rather than
    pay this spell's mana cost.
    Counter target spell unless its controller pays {1}.

    RULE 118.9's alternative cost now ships (MEC-15) as `alt_cost`'s
    ``return_to_hand`` key — the same subtype-word shape `game/costs.py`'s
    `ActivationCost.return_to_hand` already uses for an activated ability's
    "Return a Forest you control…" cost (Quirion Ranger-shaped), reused
    here for a spell's alternative *cast* cost instead. No condition:
    always available. Still also fully castable at its printed {1}{U};
    the "unless controller pays" half is the existing `CounterSpellEffect.
    unless_pays` primitive (Mana Leak's own shape).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("counter", {"unless_pays": "1"})],
        ),
        AbilitySpec(
            "spell_effect",
            [],
            alt_cost={"return_to_hand": "island"},
        ),
    ]


register("Daze", _daze)

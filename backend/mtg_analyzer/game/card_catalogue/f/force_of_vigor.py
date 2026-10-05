from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _force_of_vigor() -> list[AbilitySpec]:
    """If it's not your turn, you may exile a green card from your hand
    rather than pay this spell's mana cost.
    Destroy up to two target artifacts and/or enchantments.

    RULE 118.9's alternative cost now ships (MEC-15), same "if it's not
    your turn" gate as Force of Negation just above. Still also fully
    castable at its printed {2}{G}{G}; the "up to two" destroy is the
    already-shipped RULE 115.1a N>=2 idiom (`DestroyEffect(count=2,
    optional=True)`).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy", {
                "target_kind": "artifact_or_enchantment", "count": 2, "optional": True,
            })],
        ),
        AbilitySpec(
            "spell_effect",
            [],
            alt_cost={"exile_hand_card_color": "G", "condition": {"not_your_turn": True}},
        ),
    ]


register("Force of Vigor", _force_of_vigor)

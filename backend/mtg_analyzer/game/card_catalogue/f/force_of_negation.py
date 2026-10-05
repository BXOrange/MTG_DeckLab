from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _force_of_negation() -> list[AbilitySpec]:
    """If it's not your turn, you may exile a blue card from your hand
    rather than pay this spell's mana cost.
    Counter target noncreature spell. If that spell is countered this way,
    exile it instead of putting it into its owner's graveyard.

    RULE 118.9's alternative cost now ships (MEC-15), gated by the
    `alt_cost` dict's own ``condition`` key (`ALLOWED_FREE_CAST_CONDITION_
    KEYS`'s ``not_your_turn`` — shared with `free_cast_condition`'s own
    vocabulary/evaluator, see `condition_query.free_cast_condition_holds`).

    **Documented simplification**: the "exile instead of graveyard" rider
    is still dropped (a real but narrow gap — the counter succeeds either
    way, only the destination zone differs). Still also fully castable at
    its printed {1}{U}{U}.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("counter", {"noncreature": True})],
        ),
        AbilitySpec(
            "spell_effect",
            [],
            alt_cost={"exile_hand_card_color": "U", "condition": {"not_your_turn": True}},
        ),
    ]


register("Force of Negation", _force_of_negation)

from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _otawara_soaring_city() -> list[AbilitySpec]:
    """{T}: Add {U}.
    Channel — {3}{U}, Discard this card: Return target artifact, creature,
    enchantment, or planeswalker to its owner's hand. This ability costs
    {1} less to activate for each legendary creature you control.

    Same Channel/`dynamic_reduction` shape as `Eiganjo, Seat of the
    Empire`/`Boseiju, Who Endures` (MEC-12) — the mana ability binds
    automatically off the printed "{T}: Add {U}." text, and the per-
    legendary-creature discount is `costs.ActivationCost.dynamic_reduction`
    with the same `legendary_creatures_you_control` count_selector. The
    bounce targets `targeting.py`'s new `artifact_creature_enchantment_
    or_planeswalker` kind (MEC-12) — the four-permanent-type union this
    card's own printed wording needs, not yet used by any other card.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec(
                "return_to_hand",
                {"target_kind": "artifact_creature_enchantment_or_planeswalker"},
            )],
            cost={
                "text": "{3}{U}, Discard this card",
                "dynamic_reduction": {
                    "count_selector": "legendary_creatures_you_control",
                    "generic_per": 1,
                },
            },
        ),
    ]


register("Otawara, Soaring City", _otawara_soaring_city)

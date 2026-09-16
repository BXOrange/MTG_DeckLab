from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _shifting_woodland() -> list[AbilitySpec]:
    """This land enters tapped unless you control a Forest.
    {T}: Add {G}.
    Delirium — {2}{G}{G}: This land becomes a copy of target permanent
    card in your graveyard until end of turn. Activate only if there are
    four or more card types among cards in your graveyard.

    — MEC-43. The enters-tapped clause is read straight off oracle text by
    `land_tap_condition` independent of catalogue registration, and the
    mana ability is a plain RULE 605 ability — neither needs authoring
    here. The Delirium-gated copy ability is `BecomeCopyUntilEndOfTurnEffect`
    retargeted at the new ``"graveyard_permanent"`` kind (the existing
    graveyard-target family's own ``"permanent"`` filter, own-graveyard
    scoped), gated by `ActivationCost.activation_condition` reusing RULE
    702.137 Delirium's existing `static_conditions` kind.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("become_copy_until_eot", {"target_kind": "graveyard_permanent"})],
            cost={
                "text": "{2}{G}{G}",
                "activation_condition": {"kind": "card_types_in_graveyard_at_least", "amount": 4},
            },
        ),
    ]


register("Shifting Woodland", _shifting_woodland)

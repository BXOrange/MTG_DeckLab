from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _talon_gates_of_madara() -> list[AbilitySpec]:
    """When this land enters, up to one target creature phases out.
    {T}: Add {C}.
    {1}, {T}: Add one mana of any color.
    {4}: Put this card from your hand onto the battlefield.

    — Vivi B4 batch. The two mana abilities are already oracle-parsed
    (RULE 605); only the ETB phase-out trigger (`PhaseOutEffect`) and the
    new `PutSelfOntoBattlefieldFromHandEffect`/`ActivationCost.hand_zone`
    ("play this land from hand for a generic cost, bypassing RULE 305's
    per-turn land drop — an activated ability, not a land play") needed
    hand-authoring.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("phase_out", {"target_kind": "creature", "optional": True})],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("put_self_onto_battlefield_from_hand", {})],
            cost="{4}",
        ),
    ]


register("Talon Gates of Madara", _talon_gates_of_madara)

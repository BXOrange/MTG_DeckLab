from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: The shared activation cost of both modes.
_COST = {"text": "{2}, {T}, Remove X counters from an artifact or creature you control"}


def _moxite_refinery() -> list[AbilitySpec]:
    """{2}, {T}, Remove X counters from an artifact or creature you control:
    Choose one. Activate only as a sorcery.
    • Put X charge counters on target artifact.
    • Put X +1/+1 counters on target creature.

    — PLAY-ALL Step 2 (Counter Intelligence). The cost parses since
    PARSER_VERSION 588 (`cost_text._FROM_SOURCE`'s one-holder phrase takes an
    "or" pair -> ``remove_counters_from = artifact_or_creature``). "Choose one"
    is modelled as **two activated abilities, one per mode**: the mode is chosen
    as the ability is activated, so picking the ability *is* the choice and each
    mode keeps its own target (RULE 602.2b announces the choice before the
    cost either way). X is the announced X, shared by cost and effect.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("add_counters", {"count": "x", "kind": "charge", "target_kind": "artifact"}),
                EffectSpec("sorcery_speed_marker", {}),
            ],
            cost=dict(_COST),
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("add_counters", {"count": "x", "kind": "+1/+1", "target_kind": "creature"}),
                EffectSpec("sorcery_speed_marker", {}),
            ],
            cost=dict(_COST),
        ),
    ]


register("Moxite Refinery", _moxite_refinery)

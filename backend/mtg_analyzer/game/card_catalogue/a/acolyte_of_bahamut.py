from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _acolyte_of_bahamut() -> list[AbilitySpec]:
    """Commander creatures you own have "The first Dragon spell you cast
    each turn costs {2} less to cast."

    — PAR-32 / MEC-60. Hand-authored: the quoted body is a cost-reduction
    static (already MEC-55-grantable via `grant_static_ability`'s
    ``static_specs``) whose ``active_if`` needs a "haven't cast one of
    these yet this turn" gate no existing `static_conditions` kind
    expressed. New `first_subtype_spell_this_turn` condition
    (`GameState.creature_type_spells_cast_this_turn`, populated in
    `RulesEngine._track_spell_cast` off each cast object's live subtypes)
    combines with the pre-existing `cost_reduction` machinery's
    ``spell_subtype``/``active_if`` params — no change needed to
    `continuous.cost_reduction_for` itself, which already read both.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("grant_static_ability", {
                    "affects": "commander_creatures_you_own",
                    "static_specs": [
                        {"type": "cost_reduction", "params": {
                            "affects": "your_spells",
                            "generic": 2,
                            "spell_subtype": "Dragon",
                            "active_if": {
                                "kind": "first_subtype_spell_this_turn",
                                "subtype": "Dragon",
                            },
                        }},
                    ],
                }),
            ],
        ),
    ]


register("Acolyte of Bahamut", _acolyte_of_bahamut)

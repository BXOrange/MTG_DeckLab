
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nezumi_graverobber_nighteyes_the_desecrator() -> list[AbilitySpec]:
    "{1}{B}: Exile target card from an opponent's graveyard. If no cards are in that graveyard, flip this creature."
    return [
        AbilitySpec("activated", [
            EffectSpec("exile", {"target_kind": "opponent_graveyard_card"}),
            EffectSpec("if_else", {"condition": {"kind": "amount_compare", "op": "eq",
                "left": {"kind": "resource", "resource": "graveyard_size", "of": "previous_subject"}, "right": {"kind": "fixed", "amount": 0}},
                "then": [{"type": "flip", "params": {}}]}),
        ], cost={"mana": "{1}{B}"}),
    ]


register('Nezumi Graverobber', _nezumi_graverobber_nighteyes_the_desecrator)


def _nighteyes_the_desecrator() -> list[AbilitySpec]:
    "{4}{B}: Put target creature card from a graveyard onto the battlefield under your control."
    return [AbilitySpec("activated", [EffectSpec("return_from_graveyard", {
        "target_kind": "any_graveyard_creature", "under_your_control": True,
    })], cost={"mana": "{4}{B}"})]


register("Nighteyes the Desecrator", _nighteyes_the_desecrator)

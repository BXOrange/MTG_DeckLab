
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _queen_allenal_of_ruadach() -> list[AbilitySpec]:
    "Queen Allenal of Ruadach's power and toughness are each equal to the number of creatures you control.\nIf one or more creature tokens would be created under your control, those tokens plus a 1/1 white Soldier creature token are created instead."
    return [
        AbilitySpec(
            'static',
            [EffectSpec('pt_cda', {"affects": 'self', "power_count": {'zone': 'battlefield', 'of': 'you', 'filter': {'card_type': 'creature'}}, "toughness_count": {'zone': 'battlefield', 'of': 'you', 'filter': {'card_type': 'creature'}}})],
            raw_text="~'s power and toughness are each equal to the number of creatures you control.",
        ),
        AbilitySpec("replacement", [EffectSpec("additional_creature_tokens", {
            "only_creature": True, "fixed_amount": 1, "token_name": "Soldier",
            "power": 1, "toughness": 1, "colors": ["W"], "subtypes": ["Soldier"],
        })]),
    ]


register('Queen Allenal of Ruadach', _queen_allenal_of_ruadach)

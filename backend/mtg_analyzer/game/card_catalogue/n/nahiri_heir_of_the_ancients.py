from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nahiri_heir_of_the_ancients() -> list[AbilitySpec]:
    """+1: Create a 1/1 white Kor Warrior creature token. You may attach an
    Equipment you control to it.
    −2: Look at the top six cards of your library. You may reveal a Warrior
    or Equipment card from among them and put it into your hand. Put the
    rest on the bottom of your library in a random order.
    −3: Nahiri deals damage to target creature or planeswalker equal to
    twice the number of Equipment you control.

    — Nahiri, Heir of the Ancients. Only +1 is modeled: −2 needs a "look at
    top N, take a matching one, bottom the rest" mechanic distinct from a
    whole-library `search` (not implemented); −3 needs a dynamic damage
    amount computed at resolution (no `DealDamageEffect` "amount equals a
    count" mode exists yet). Both are documented gaps rather than guessed
    approximations.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("seq", {"effects": [
                {"type": "create_token", "params": {
                    "token_name": "Kor Warrior", "power": 1, "toughness": 1,
                    "colors": ["W"], "subtypes": ["Kor", "Warrior"],
                }},
                {"type": "optional", "params": {"effects": [
                    {"type": "attach", "params": {
                        "target_kind": "created", "mover": "target",
                        "mover_kind": "equipment_you_control", "mover_optional": True,
                    }},
                ]}},
            ]})],
            cost={"loyalty": 1},
        )
    ]


register("Nahiri, Heir of the Ancients", _nahiri_heir_of_the_ancients)

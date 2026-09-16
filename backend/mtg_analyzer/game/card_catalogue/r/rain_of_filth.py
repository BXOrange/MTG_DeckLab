from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rain_of_filth() -> list[AbilitySpec]:
    """Until end of turn, lands you control gain "Sacrifice this land:
    Add {B}."

    — MEC-43. `GrantUntilEffect` wrapping the existing quoted-mana-ability
    grant (`grant_mana_ability`, Tyvar Kell's "Elves you control have
    '{T}: Add {B}.'") with its own ``cost`` upgrade (MEC-25, Goldspan
    Dragon) set to a self-sacrifice instead of the bare default {T} — an
    *added* ability on each land, not a replacement of anything printed,
    since a self-sacrifice cost never matches a land's own {T}-shaped mana
    ability. Untargeted (``target_kind=None``): the static's own ``affects``
    already scopes it to "lands you control".
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("grant_until", {
                "static": {
                    "type": "grant_mana_ability",
                    "params": {
                        "mana": [{"color": "B", "amount": 1}],
                        "cost": {"sacrifice": "self"},
                        "affects": "lands_you_control",
                    },
                },
                "duration": "end_of_turn",
                "target_kind": None,
            })],
        ),
    ]


register("Rain of Filth", _rain_of_filth)

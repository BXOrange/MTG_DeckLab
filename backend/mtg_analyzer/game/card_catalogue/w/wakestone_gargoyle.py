from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _wakestone_gargoyle() -> list[AbilitySpec]:
    """Defender, flying
    {1}{W}: Creatures you control with defender can attack this turn as though they didn't have defender.

    — PLAY-ALL (Abzan Armor). Keywords are the catalogue's. `combat_restriction_this_turn` over a structured group (your
    creatures with defender) granting ``attacks_as_though_no_defender`` until end of turn.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("combat_restriction_this_turn", {
                "restriction": {"kind": "attacks_as_though_no_defender"},
                "selector": {
                    "zone": "battlefield", "of": "you", "filter": {"card_type": "creature", "keyword": "defender"},
                },
            })],
            cost={"text": "{1}{W}"},
        ),
    ]


register("Wakestone Gargoyle", _wakestone_gargoyle)

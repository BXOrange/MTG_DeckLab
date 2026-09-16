from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _new_way_forward() -> list[AbilitySpec]:
    """The next time a source of your choice would deal damage to you this
    turn, prevent that damage. When damage is prevented this way, New Way
    Forward deals that much damage to that source's controller and you
    draw that many cards.

    — Two independent riders off the same prevented amount
    (``rider`` as a list — MEC-30's new list form of `RulesEngine.
    apply_prevent_rider`, first real card to need it).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("request_prevent_damage_source", {
                "amount": "all",
                "rider": [
                    {"kind": "deal_damage_to_source_controller"},
                    {"kind": "draw_cards", "recipient": "you"},
                ],
            })],
        ),
    ]


register("New Way Forward", _new_way_forward)

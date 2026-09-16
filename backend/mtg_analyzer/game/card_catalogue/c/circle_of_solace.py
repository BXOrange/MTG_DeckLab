from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _circle_of_solace() -> list[AbilitySpec]:
    """As this enchantment enters, choose a creature type.
    {1}{W}: The next time a creature of the chosen type would deal damage
    to you this turn, prevent that damage.

    — The ETB creature-type choice is the ordinary ``choose_creature_type_
    on_enter`` replacement (Adaptive Automaton's own precedent, stamping
    `GameObject.chosen_type`); the shield reads it back via MEC-30's new
    ``source_filter={"card_type": "creature", "subtype_from_source": True}``.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_creature_type_on_enter", {})],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"card_type": "creature", "subtype_from_source": True},
                "amount": "all",
            })],
            cost={"mana": "{1}{W}"},
        ),
    ]


register("Circle of Solace", _circle_of_solace)

from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _burnt_offering() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, sacrifice a creature.
    Add X mana in any combination of {B} and/or {R}, where X is the
    sacrificed creature's mana value.

    — MEC-43. The same "any combination of `<colors>`" simplification
    (`AddManaEffect.any_color_choices`) Culling Ritual already established,
    with the amount now driven by the widened ``amount_selector`` ANY-branch
    reading `GameObject.sacrificed_cost_mana_value` (stamped by the
    RULE 601.2b additional-cost payment, the same channel Eldritch
    Evolution/Neoform already use).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("add_mana", {
                "colors": ["ANY"], "any_color_choices": ["B", "R"],
                "amount_selector": "sacrificed_cost_mana_value",
            })],
            additional_cost={"sacrifice": "creature"},
        ),
    ]


register("Burnt Offering", _burnt_offering)

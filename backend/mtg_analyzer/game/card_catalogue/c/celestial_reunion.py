from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _celestial_reunion() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, you may choose a creature
    type and behold two creatures of that type.
    Search your library for a creature card with mana value X or less,
    reveal it, put it into your hand, then shuffle. If this spell's
    additional cost was paid and the revealed card is the chosen type, put
    that card onto the battlefield instead of putting it into your hand.

    — PAR-30 (Collect Evidence / Forage / Blight residue). The optional
    additional cost is `behold_two_shared_type` (`GameEngine._behold_two_
    shared_type` picks a creature type the caster has two of across their
    battlefield + hand, stamps it on `GameObject.chosen_type`, sets
    `additional_cost_paid`). The body is `celestial_reunion_search` — see
    that effect's docstring for the ``destination_if`` conditional
    destination.
    """
    return [
        AbilitySpec(
            "spell_effect", [],
            additional_cost={"behold_two_shared_type": True},
            additional_cost_optional=True,
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("celestial_reunion_search", {})],
        ),
    ]


register("Celestial Reunion", _celestial_reunion)

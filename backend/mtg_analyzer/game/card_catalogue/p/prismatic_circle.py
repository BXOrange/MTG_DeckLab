from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _prismatic_circle() -> list[AbilitySpec]:
    """Cumulative upkeep {1}
    As this enchantment enters, choose a color.
    {1}: The next time a source of your choice of the chosen color would
    deal damage to you this turn, prevent that damage.

    — Cumulative upkeep is the ordinary RULE 702.24 keyword fold-in
    (MEC-16, unaffected by this registration). The rest is Story Circle's
    own shape at a cheaper activation cost.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_color_on_enter", {})],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color_from_source": True}, "amount": "all",
            })],
            cost={"mana": "{1}"},
        ),
    ]


register("Prismatic Circle", _prismatic_circle)

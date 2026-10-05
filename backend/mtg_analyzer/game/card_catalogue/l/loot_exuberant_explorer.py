from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _loot_exuberant_explorer() -> list[AbilitySpec]:
    """You may play an additional land on each of your turns.
    {4}{G}{G}, {T}: Look at the top six cards of your library. You may reveal a creature card with mana
    value less than or equal to the number of lands you control from among them and put it onto the
    battlefield. Put the rest on the bottom in a random order.

    — Tramplesaurus Rex deck batch. The extra land drop is the parser's own claim. The ability is the
    PAR-144 dig `inspect_top_choose` (six cards, one optional pick onto the battlefield, the rest to
    the bottom at random) with the pick restricted to creature cards whose mana value is at most the
    new ``lands_you_control`` criteria bound, counted as the ability resolves.
    """
    return [
        AbilitySpec("static", [EffectSpec("extra_land_drop", {"affects": "you", "count": 1})]),
        AbilitySpec(
            "activated",
            [EffectSpec("inspect_top_choose", {
                "count": 6, "action": "library_to_battlefield", "max_picks": 1, "optional": True,
                "criteria": {"type": "Creature", "max_mana_value": "lands_you_control"},
                "rest_destination": "library_bottom_random",
            })],
            cost={"text": "{4}{g}{g}, {t}"},
        ),
    ]


register("Loot, Exuberant Explorer", _loot_exuberant_explorer)

from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: Printed "top seven cards".
_LOOK_AT = 7


def _turntimber_symbiosis() -> list[AbilitySpec]:
    """Look at the top seven cards of your library. You may put a creature card
    from among them onto the battlefield. If that card has mana value 3 or
    less, it enters with three additional +1/+1 counters on it. Put the rest on
    the bottom of your library in a random order.

    — PLAY-ALL (Raggadragga). `inspect_top_choose` gives a cheap selected
    creature its three entry counters before ETB triggers. The cached modal
    back face is handled by ordinary land play: its printed optional life
    payment controls tapped entry, and its text supplies green mana.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("inspect_top_choose", {
                "count": _LOOK_AT, "action": "library_to_battlefield_cheap_bonus", "optional": True, "max_picks": 1,
                "criteria": {"type": "creature"}, "rest_destination": "library_bottom_random",
            })],
        ),
    ]


register("Turntimber Symbiosis", _turntimber_symbiosis)

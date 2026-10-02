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

    — PLAY-ALL Step 2 (Raggadragga). PAR-144's `inspect_top_choose` (one optional
    creature pick, the rest to the bottom in random order) with the new choose
    action `library_to_battlefield_cheap_bonus`: it stamps
    `GameObject.entry_bonus_counters` (mana value <= 3 -> three +1/+1) which
    `_apply_entry_counters` applies *as it enters*, so the counters are there
    for its own ETB triggers. Registered under the front-face name (the DFC's `//`
    fallback finds it). **The back face, Turntimber, Serpentine Wood (a land), is not
    authored** — the card cache holds only the front face's text for this card, so its
    abilities cannot be verified on this PC.
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

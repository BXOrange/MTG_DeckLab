from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _wheel_of_misfortune() -> list[AbilitySpec]:
    """Each player secretly chooses a number 0 or greater, then all
    players reveal those numbers simultaneously and determine the
    highest and lowest numbers revealed this way. Wheel of Misfortune
    deals damage equal to the highest number to each player who chose
    that number. Each player who didn't choose the lowest number
    discards their hand, then draws seven cards.

    — Imodane deck batch. **Documented simplification** (the whole card):
    no "secretly choose a number, then reveal simultaneously" primitive
    exists (a genuinely new interactive-choice subsystem, out of scope
    for the value of one card), so the highest/lowest voting sub-game and
    its damage aren't modeled at all. What's modeled instead is the
    card's Wheel-of-Fortune-shaped headline effect: every player
    discards their hand and draws seven — `DiscardEffect(count=99,
    scope="each_player")` is the same "count large enough to force the
    whole hand" idiom Fire Covenant's own ``count=10`` "any number" UI
    cap uses elsewhere, since `discard_choice` already forces without a
    prompt once ``count`` reaches hand size.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("discard", {"count": 99, "scope": "each_player"}),
                EffectSpec("draw", {"count": 7, "selector": "each_player"}),
            ],
        ),
    ]


register("Wheel of Misfortune", _wheel_of_misfortune)

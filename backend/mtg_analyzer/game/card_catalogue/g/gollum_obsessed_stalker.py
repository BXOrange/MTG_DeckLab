from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _gollum_obsessed_stalker() -> list[AbilitySpec]:
    """Skulk (This creature can't be blocked by creatures with greater
    power.)
    At the beginning of your end step, each opponent dealt combat damage
    this game by a creature named Gollum, Obsessed Stalker loses life
    equal to the amount of life you gained this turn.

    Simplified: narrowed to "each opponent loses life equal to the amount
    of life you gained this turn" every end step — the "only an opponent
    this specific creature has ever connected with" scoping isn't tracked
    (no "dealt combat damage by a creature named X, ever" history exists);
    in practice this only differs when Gollum himself hasn't dealt combat
    damage to anyone yet, a narrow early-game window.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {
                "selector": "each_opponent",
                "amount_from_count_selector": "life_gained_this_turn",
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
    ]


register("Gollum, Obsessed Stalker", _gollum_obsessed_stalker)

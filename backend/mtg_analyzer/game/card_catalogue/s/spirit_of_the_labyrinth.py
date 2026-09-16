from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _spirit_of_the_labyrinth() -> list[AbilitySpec]:
    """Each player can't draw more than one card each turn.

    — Spirit of the Labyrinth. A new `draw_limit` static layer this batch,
    the draw-side mirror of the existing `cast_limit` family (Eidolon of
    Rhetoric/Rule of Law/Archon of Emeria) — `RulesEngine._single_draw`
    consults `continuous.max_draws_per_turn` against a new per-player
    `GameState.cards_drawn_this_turn` counter before each individual draw,
    the same "flat global cap, most restrictive wins" shape.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("draw_limit", {"max_per_turn": 1})],
        )
    ]


register("Spirit of the Labyrinth", _spirit_of_the_labyrinth)

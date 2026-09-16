from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _galvanic_relay() -> list[AbilitySpec]:
    """Exile the top card of your library. During your next turn, you may
    play that card.
    Storm (When you cast this spell, copy it for each spell cast before
    it this turn.)

    — Imodane deck batch. Storm is a RULE 702 keyword, auto-bound. The
    exile clause is the shipped `impulsive_draw` (Light Up the Stage-
    shaped) — "during your next turn" is `same_turn_only=False`'s own
    "until the end of your next turn" window, a superset of the printed
    text rather than a narrower one.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("impulsive_draw", {"count": 1})],
        ),
    ]


register("Galvanic Relay", _galvanic_relay)

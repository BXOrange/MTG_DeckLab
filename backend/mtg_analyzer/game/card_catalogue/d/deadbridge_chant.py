from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: The printed "mill ten cards".
_MILL_COUNT = 10


def _deadbridge_chant() -> list[AbilitySpec]:
    """When this enchantment enters, mill ten cards.
    At the beginning of your upkeep, choose a card at random in your graveyard. If it's a creature card, put it onto the battlefield. Otherwise, put it into your hand.

    — PLAY-ALL (Death Toll). The ETB is a plain mill. The upkeep trigger is `return_from_graveyard` in its ``at_random`` mode (RULE 706:
    one card drawn from your graveyard with the engine's reproducible randomness) with ``else_destination="hand"`` for a non-creature card.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("mill", {"count": _MILL_COUNT})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_card", "at_random": 1, "destination": "battlefield", "else_destination": "hand",
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
    ]


register("Deadbridge Chant", _deadbridge_chant)

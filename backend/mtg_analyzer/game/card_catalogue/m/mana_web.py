from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mana_web() -> list[AbilitySpec]:
    """Whenever a land an opponent controls is tapped for mana, tap all
    lands that player controls that could produce any type of mana that land
    could produce.

    — Mana Web. *Not* a mana ability (it produces none), so unlike Wild
    Growth/Kinnan above it uses the stack like any ordinary trigger.

    Both halves of "that player" / "that land" come from the firing event
    (`GameContext.trigger_event`). The reference land's production is
    re-derived from `game/mana_abilities.py` rather than read off the
    event's ``produced`` payload, because RULE 605.1a's wording is about
    what a land *could* produce: a dual land tapped for {U} still locks
    down every land making {U} **or** its other colour, which is the
    difference between Mana Web being a real prison piece and a rounding
    error.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("tap_matching_lands", {})],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "group", "controller": "not_you", "type": "land"},
            },
        ),
    ]


register("Mana Web", _mana_web)

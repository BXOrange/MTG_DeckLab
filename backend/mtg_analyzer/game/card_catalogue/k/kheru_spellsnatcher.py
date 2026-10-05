from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kheru_spellsnatcher() -> list[AbilitySpec]:
    """Morph {4}{U}{U} (You may cast this card face down as a 2/2 creature for {3}. Turn it face up any time for its morph cost.)
    When this creature is turned face up, counter target spell. If that spell is countered this way, exile it instead of putting it into its owner's graveyard. You may cast that card without paying its mana cost for as long as it remains exiled.

    — PLAY-ALL (Jump Scare!). Morph is a keyword. A self `TURNED_FACE_UP` trigger over `counter` with the new
    ``exile_standing_free_cast`` (Transcendent Dragon's exile, then a standing, never-expiring free cast of the exiled card
    for the Spellsnatcher's controller — `GameState.exile_cast_condition` + `free_cast_instance_ids`).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("counter", {"exile_standing_free_cast": True})],
            trigger={"event": EventType.TURNED_FACE_UP, "condition": {"subject": "self"}},
        ),
    ]


register("Kheru Spellsnatcher", _kheru_spellsnatcher)

from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _firemane_commando() -> list[AbilitySpec]:
    """Flying
    Whenever you attack with two or more creatures, draw a card.
    Whenever another player attacks with two or more creatures, they draw a
    card if none of those creatures attacked you.

    Documented simplification: only the "you attack" half is modeled; the
    symmetric "another player" gift-draw is dropped (a rare political
    corner)."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={"event": EventType.PLAYER_ATTACKED, "condition": {"subject": "you"},
                     "attackers_at_least": 2},
        ),
    ]


register("Firemane Commando", _firemane_commando)

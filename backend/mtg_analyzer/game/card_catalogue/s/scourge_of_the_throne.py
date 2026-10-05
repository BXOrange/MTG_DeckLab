from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _scourge_of_the_throne() -> list[AbilitySpec]:
    """Flying
    Dethrone (Whenever this creature attacks the player with the most life or tied for most life, put a
    +1/+1 counter on it.)
    Whenever this creature attacks for the first time each turn, if it's attacking the player with the most
    life or tied for most life, untap all attacking creatures. After this phase, there is an additional
    combat phase.

    — Reign of Dragons deck batch. Flying and Dethrone are keywords. The trigger is a self `ATTACKS` with
    the binder's ``attacked_player_has_most_life`` intervening-if (the Dethrone predicate) and the
    once-each-turn limiter (``limit``); the body is the mass untap of attackers followed by
    `extra_combat_phase`. **Documented simplification:** "for the first time each turn" is the limiter
    counting firings, so an earlier attack that did not meet the condition does not use it up.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("tap", {"selector": "attacking_creatures", "untap": True}),
             EffectSpec("extra_combat_phase", {})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"},
                     "attacked_player_has_most_life": True, "limit": True},
        ),
    ]


register("Scourge of the Throne", _scourge_of_the_throne)

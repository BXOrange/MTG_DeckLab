from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _transcendent_dragon() -> list[AbilitySpec]:
    """Flash
    Flying
    When this creature enters, if you cast it, counter target spell. If that spell is countered
    this way, exile it instead of putting it into its owner's graveyard, then you may cast it
    without paying its mana cost.

    — Jeskai Striker deck batch. Flash/Flying are keywords. The "if you cast it" intervening-if
    (RULE 603.4) is the ``was_cast`` flag, on the trigger and again on the effect (the Deathbringer
    Regent shape). The body is `counter` with ``exile_then_cast_free``: the countered spell goes to
    exile (`counter_spell(exile_instead=True)` — not countered when it can't be) and its *new*
    controller, the Dragon's, is offered a free cast through RULE 608.2g's resolution play.
    """
    gate = {"kind": "flag", "flag": "was_cast"}
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("counter", {"exile_then_cast_free": True}, condition=gate)],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "self"},
                "active_if": gate,
            },
        ),
    ]


register("Transcendent Dragon", _transcendent_dragon)

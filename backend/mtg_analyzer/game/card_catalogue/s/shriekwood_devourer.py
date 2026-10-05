from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _shriekwood_devourer() -> list[AbilitySpec]:
    """Trample
    Whenever you attack with one or more creatures, untap up to X lands, where X is the greatest power among those creatures.

    — PLAY-ALL (Jump Scare!). Trample is a keyword. The head is the parser's "whenever you attack" trigger; the body is the
    parser's untap-lands `choose_objects`, with its count read by the new ``count_amount`` operand off the captured
    ``matching_attacker_greatest_power`` (`trigger_quantities.capture_attackers`).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("choose_objects", {
                "action": "untap", "what": "land", "optional": True,
                "count_amount": {"kind": "trigger_event", "field": "matching_attacker_greatest_power"},
                "prompt": "Wähle bis zu X Länder zum Enttappen",
            })],
            trigger={
                "event": EventType.ATTACKERS_DECLARED, "condition": {"subject": "you"},
                "attackers_declared": {"filter": {"card_type": "creature"}, "min": 1},
            },
        ),
    ]


register("Shriekwood Devourer", _shriekwood_devourer)

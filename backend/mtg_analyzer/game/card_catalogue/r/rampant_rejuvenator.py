from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rampant_rejuvenator() -> list[AbilitySpec]:
    """This creature enters with two +1/+1 counters on it.
    When this creature dies, search your library for up to X basic land cards, where X is this creature's power, put them onto the
    battlefield, then shuffle.

    — PLAY-ALL (Counter Blitz). The entry counters are oracle-derived. The dies trigger `bind`s the dying creature's last-known power
    (the DIES event's ``power`` snapshot via ``of: trigger_subject``, RULE 400.7/603.10a) into `search`'s ``count``.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("bind", {
                "name": "x", "amount": {"kind": "characteristic", "characteristic": "power", "of": "trigger_subject"},
                "effects": [{"type": "search", "params": {
                    "criteria": {"basic": True, "type": "Land"}, "destination": "battlefield", "count": "$x",
                    "optional": True,
                }}],
            })],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
        ),
    ]


register("Rampant Rejuvenator", _rampant_rejuvenator)

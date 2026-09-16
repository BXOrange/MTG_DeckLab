from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _claim_jumper() -> list[AbilitySpec]:
    """Vigilance
    When this creature enters, if an opponent controls more lands than you,
    you may search your library for a Plains card and put it onto the
    battlefield tapped. Then if an opponent controls more lands than you,
    repeat this process once. If you search your library this way, shuffle.

    Documented simplification: "repeat this process once" is modeled as a
    single search for *up to two* Plains onto the battlefield tapped."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"type": "plains"}, "count": 2,
                "destination": "battlefield_tapped", "optional": True,
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"},
                "active_if": {"kind": "opponent_controls_more_lands"},
            },
        ),
    ]


register("Claim Jumper", _claim_jumper)

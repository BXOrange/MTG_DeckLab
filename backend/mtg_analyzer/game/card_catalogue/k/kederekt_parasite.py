from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kederekt_parasite() -> list[AbilitySpec]:
    """Whenever an opponent draws a card, if you control a red permanent, you may have this creature deal 1 damage to that player.

    — PLAY-ALL (Endless Punishment). The parser's DRAW head over an opponent with `damage` to the ``event_player`` (Spellshock's shape) — but it drops the
    "if you control a red permanent" clause, so the RULE 603.4 intervening-if is authored: a trigger ``active_if`` `control_count` over red permanents you
    control. The "you may" is the trigger's own ``optional``.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "selector": "event_player"})],
            trigger={
                "event": EventType.DRAW, "condition": {"subject": "group", "controller": "not_you"},
                "active_if": {"kind": "control_count", "min": 1, "selector": {
                    "zone": "battlefield", "of": "you", "filter": {"color": "R"}}},
            },
            optional=True,
        ),
    ]


register("Kederekt Parasite", _kederekt_parasite)

from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _coveted_jewel() -> list[AbilitySpec]:
    """When this artifact enters, draw three cards.
    {T}: Add three mana of any one color.
    Whenever one or more creatures an opponent controls attack you and aren't blocked, that player draws three
    cards and gains control of this artifact. Untap it.

    — Peace Offering deck batch. The ETB draw is the parser's claim; the three-mana tap ability is derived from
    the oracle text by `mana_abilities`, outside the spec list. The steal is an `ATTACKER_UNBLOCKED` trigger
    scoped by ``first_unblocked_attacker_at_you`` (the event fires per attacker, "one or more" is one trigger per
    attacking opponent): `draw` for the event's player, `gain_control_by_source` with ``recipient="event_player"``
    (control moves to that player, indefinitely), then `untap_self`.
    """
    return [
        AbilitySpec(
            "triggered", [EffectSpec("draw", {"count": 3})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("draw", {"count": 3, "selector": "event_player"}),
                EffectSpec("gain_control_by_source", {"recipient": "event_player"}),
                EffectSpec("untap_self", {}),
            ],
            trigger={"event": EventType.ATTACKER_UNBLOCKED, "first_unblocked_attacker_at_you": True},
        ),
    ]


register("Coveted Jewel", _coveted_jewel)

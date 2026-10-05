from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: Poison counters an opponent gets for sacrificing a noncreature token.
POISON_PER_SACRIFICE = 2


def _bloodroot_apothecary() -> list[AbilitySpec]:
    """Toxic 2 (Players dealt combat damage by this creature also get two poison counters. A player with ten
    or more poison counters loses the game.)
    When this creature enters, you and target opponent each create a Treasure token.
    Whenever an opponent sacrifices a noncreature token, that player gets two poison counters.

    — Peace Offering deck batch. Toxic is the engine's own keyword (read off the card text). The ETB is one
    `create_token` for you and one for the targeted opponent (``creators="target"``). The sacrifice trigger is
    `EventType.SACRIFICE` scoped to a noncreature token an opponent controlled (the group filter's ``token``
    and ``without_card_type`` keys, read off the event's own payload), poisoning the player the event names.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("create_token", {"token_name": "Treasure", "count": 1}),
                EffectSpec("create_token", {
                    "token_name": "Treasure", "count": 1, "creators": "target", "target_kind": "opponent",
                }),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_player_counters", {
                "amount": POISON_PER_SACRIFICE, "kind": "poison", "player": {"of": "event_player"},
            })],
            trigger={
                "event": EventType.SACRIFICE,
                "condition": {
                    "subject": "group", "controller": "not_you",
                    "filter": {"token": True, "without_card_type": "creature"},
                },
            },
        ),
    ]


register("Bloodroot Apothecary", _bloodroot_apothecary)

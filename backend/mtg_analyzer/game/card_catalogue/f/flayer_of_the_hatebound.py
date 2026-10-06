from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _flayer_of_the_hatebound() -> list[AbilitySpec]:
    """Undying
    Whenever this creature or another creature enters from your graveyard, that creature deals damage equal to its power to any target.

    — PLAY-ALL (Revival Trance). Undying is a keyword. A group enters trigger (any creature, ``from_zone`` graveyard — cast
    from the graveyard does not count) over `damage` of the entering creature's power, dealt *by* that creature
    (``dealer_event_key``). The Flayer's own undying return fires it too.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {
                "amount": {"kind": "characteristic", "of": "trigger_subject", "characteristic": "power"},
                "target_kind": "any", "dealer_event_key": "instance_id",
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "controller": "you", "other": False, "filter": {"card_type": "creature"}},
                "filter": {"from_zone": "graveyard"},
            },
        ),
    ]


register("Flayer of the Hatebound", _flayer_of_the_hatebound)

from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tataru_taru() -> list[AbilitySpec]:
    """When Tataru Taru enters, you draw a card and target opponent may
    draw a card.
    Scions' Secretary — Whenever an opponent draws a card, if it isn't
    that player's turn, create a tapped Treasure token. This ability
    triggers only once each turn.

    — MEC-43. The ETB is a plain self-draw plus an optional targeted
    opponent draw. The second ability reuses `effect_binder`'s existing
    ``not_controllers_turn`` predicate (checked against the firing DRAW
    event's own actor, exactly "if it isn't **that player's** turn") and
    `TriggeredAbility.once_per_turn`.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("draw", {"count": 1}),
                EffectSpec("draw", {"count": 1, "target_kind": "opponent", "optional": True}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "token_name": "Treasure", "subtypes": ["Treasure"],
                "is_artifact": True, "tapped": True,
            })],
            trigger={
                "event": EventType.DRAW,
                "condition": {"subject": "group", "controller": "not_you"},
                "not_controllers_turn": True,
                "limit": True,
            },
        ),
    ]


register("Tataru Taru", _tataru_taru)

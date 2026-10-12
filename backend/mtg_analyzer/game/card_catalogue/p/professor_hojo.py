from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _professor_hojo() -> list[AbilitySpec]:
    """The first activated ability you activate during your turn that targets a creature you control costs {2} less to activate.
    Whenever one or more creatures you control become the target of an activated ability, draw a card. This ability triggers only once each turn.

    — PLAY-ALL (Limit Break). The discount reads the announced targets and
    earlier qualifying activations this turn. The draw filters activated
    abilities, including an opponent's, and triggers only once per turn.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "scope": "activation", "generic": 2, "first_targeting_own_creature": True, "active_if": {"kind": "your_turn"},
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1}), EffectSpec("action_once_per_turn_marker", {})],
            trigger={
                "event": EventType.BECOMES_TARGET,
                "filter": {"item_category": "activated_ability", "target_creature_you_control": True},
            },
        ),
    ]


register("Professor Hojo", _professor_hojo)

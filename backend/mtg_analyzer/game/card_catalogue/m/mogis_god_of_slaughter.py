from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mogis_god_of_slaughter() -> list[AbilitySpec]:
    """Indestructible
    As long as your devotion to black and red is less than seven, Mogis isn't a creature.
    At the beginning of each opponent's upkeep, Mogis deals 2 damage to that player unless they sacrifice a creature of their choice.

    — PLAY-ALL (Endless Punishment). Indestructible is a keyword and the devotion static is the parser's (`type_change` removing creature under a devotion gate).
    The upkeep trigger is a `pay_cost_then` asked of that player (``payer: event_player``) whose cost is "sacrifice a creature" and whose ``else_effects`` is the 2 damage to
    the active player — "unless" is the decline branch.
    """
    return [
        AbilitySpec("static", [EffectSpec("type_change", {
            "remove_types": ["creature"],
            "active_if": {"kind": "control_count", "selector": "devotion_to_br", "max": 6},
        })]),
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "Sacrifice a creature", "payer": "event_player", "effects": [],
                "else_effects": [{"type": "damage", "params": {"amount": 2, "selector": "active_player"}}],
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "not_you"},
        ),
    ]


register("Mogis, God of Slaughter", _mogis_god_of_slaughter)

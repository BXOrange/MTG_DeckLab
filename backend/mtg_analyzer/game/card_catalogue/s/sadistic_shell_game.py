from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sadistic_shell_game() -> list[AbilitySpec]:
    """Starting with the next opponent in turn order, each player chooses a creature you don't control. Destroy the chosen creatures.

    — PLAY-ALL (Endless Punishment). Druid of Purification's `choose_player_objects` with ``destroy_not_yours`` (every player — you included — picks a permanent the
    controller doesn't control, then all picks are destroyed at once, RULE 608.2e) restricted to creatures, no "may", and the new ``start_with_next_opponent`` seat order.
    """
    return [
        AbilitySpec("spell_effect", [EffectSpec("choose_player_objects", {
            "action": "destroy_not_yours", "player_scope": "each_player", "optional": False,
            "card_types_any": ["creature"], "start_with_next_opponent": True,
        })]),
    ]


register("Sadistic Shell Game", _sadistic_shell_game)

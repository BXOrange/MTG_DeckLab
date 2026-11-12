"""Goblin War Cry."""
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _goblin_war_cry():
    """Target opponent chooses a creature they control. Other creatures they control can't block this turn."""
    return [AbilitySpec("spell_effect", [EffectSpec("war_cry", {})])]


register('Goblin War Cry', _goblin_war_cry)

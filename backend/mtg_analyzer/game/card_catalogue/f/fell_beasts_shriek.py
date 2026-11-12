"""Fell Beast's Shriek."""
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _fell_beasts_shriek():
    """Each opponent chooses a creature they control. Tap and goad the chosen creatures. (Until your next turn, those creatures attack each combat if able and attack a player other than you if able.)
Splice onto instant or sorcery {2}{U}{R} (As you cast an instant or sorcery spell, you may reveal this card from your hand and pay its splice cost. If you do, add this card's effects to that spell.)"""
    return [
        AbilitySpec("spell_effect", [EffectSpec("fell_beast_shriek", {})]),
        AbilitySpec("keyword", [], keyword={"name": "splice", "quality": "instant_or_sorcery", "cost": "{2}{U}{R}"}),
    ]


register("Fell Beast's Shriek", _fell_beasts_shriek)

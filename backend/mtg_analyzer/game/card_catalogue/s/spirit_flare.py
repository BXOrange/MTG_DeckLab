"""Spirit Flare."""
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _spirit_flare():
    """Tap target untapped creature you control. If you do, it deals damage equal to its power to target attacking or blocking creature an opponent controls.
Flashback—{1}{W}, Pay 3 life. (You may cast this card from your graveyard for its flashback cost. Then exile it.)
"""
    return [
        AbilitySpec("spell_effect", [EffectSpec("tap_creature_strike", {})]),
        AbilitySpec("keyword", [], keyword={"name": "flashback", "cost": "{1}{W}, Pay 3 life"}),
    ]


register("Spirit Flare", _spirit_flare)

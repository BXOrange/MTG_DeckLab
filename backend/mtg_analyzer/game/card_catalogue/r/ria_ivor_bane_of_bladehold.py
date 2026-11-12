"""Ria Ivor, Bane of Bladehold."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ria_ivor_bane_of_bladehold():
    """Battle cry (Whenever this creature attacks, each other attacking creature gets +1/+0 until end of turn.)
At the beginning of combat on your turn, the next time target creature would deal combat damage to one or more players this combat, prevent that damage. If damage is prevented this way, create that many 1/1 colorless Phyrexian Mite artifact creature tokens with toxic 1 and "This token can't block."
"""
    return [AbilitySpec(
        "triggered", [EffectSpec("combat_prevention_tokens", {})],
        trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}, "phase_relation": "you"},
    )]


register("Ria Ivor, Bane of Bladehold", _ria_ivor_bane_of_bladehold)

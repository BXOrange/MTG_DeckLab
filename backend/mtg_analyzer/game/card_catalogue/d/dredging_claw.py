"""Dredging Claw."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dredging_claw():
    """Equipped creature gets +1/+0 and has menace. (It can't be blocked except by two or more creatures.)
Whenever a creature enters from your graveyard, you may attach this Equipment to it.
Equip {1}{B} ({1}{B}: Attach to target creature you control. Equip only as a sorcery.)
"""
    return [
        AbilitySpec("static", [
            EffectSpec("anthem", {"power": 1, "toughness": 0, "affects": "attached_permanent"}),
            EffectSpec("grant_keyword", {"affects": "attached_permanent", "keywords": ["menace"]}),
        ]),
        AbilitySpec("triggered", [EffectSpec("trigger_subject_referent", {
            "effects": [{"type": "attach", "params": {"check_control": False}}],
        })], trigger={
            "event": EventType.ENTERS_BATTLEFIELD,
            "condition": {"subject": "group", "controller": "any", "type": "creature", "owner": "you"},
            "filter": {"from_zone": "graveyard"},
        }, optional=True),
    ]


register("Dredging Claw", _dredging_claw)

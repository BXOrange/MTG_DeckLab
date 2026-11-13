from __future__ import annotations
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

def _arcums_sleigh():
    """{2}, {T}: Target creature gains vigilance until end of turn. Activate only during combat and only if defending player controls a snow land."""
    return [AbilitySpec('activated', [EffectSpec('pump', {'target_kind': 'creature', 'keywords': ['vigilance']})],
        cost={'text': '{2}, {T}', 'activation_condition': {'kind': 'all', 'conditions': [
            {'kind': 'during_phase', 'phase': 'combat'},
            {'kind': 'defending_player_permanent_count', 'filter': {'card_type': 'land', 'snow': True}, 'min': 1},
        ]}})]
register("Arcum's Sleigh", _arcums_sleigh)

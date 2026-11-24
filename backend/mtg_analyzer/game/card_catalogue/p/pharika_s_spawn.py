from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _pharika_s_spawn() -> list[AbilitySpec]:
    """Escape—{5}{B}, Exile three other cards from your graveyard. (You may cast this card from your graveyard for its escape cost.)
    This creature escapes with two +1/+1 counters on it. When it enters this way, each opponent sacrifices a non-Gorgon creature of their choice.
    """
    return [AbilitySpec('triggered', [EffectSpec('sacrifice', {
        'selector': 'each_opponent', 'what': 'non_gorgon_creature',
    })], trigger={
        'event': EventType.ENTERS_BATTLEFIELD, 'condition': {'subject': 'self'},
        'active_if': {'kind': 'flag', 'flag': 'cast_via_escape'},
    })]


register("Pharika's Spawn", _pharika_s_spawn,
    entry_counters={'is_x': False, 'count': 2, 'counter_type': '+1/+1', 'escape_gate': True})

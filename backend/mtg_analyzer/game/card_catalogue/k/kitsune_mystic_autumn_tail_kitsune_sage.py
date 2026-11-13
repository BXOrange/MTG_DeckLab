from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kitsune_mystic() -> list[AbilitySpec]:
    """At the beginning of the end step, if this creature is enchanted by two or more Auras, flip it."""
    gate={'kind': 'source_enchanted', 'min': 2}
    return [AbilitySpec('triggered', [EffectSpec('flip', {}, condition=dict(gate))], trigger={
        'event': EventType.STEP_BEGIN, 'filter': {'step': 'end'}, 'active_if': dict(gate),
    })]


def _autumn_tail() -> list[AbilitySpec]:
    """{1}: Attach target Aura attached to a creature to another creature."""
    return [AbilitySpec('activated', [EffectSpec('autumn_tail_attach', {})], cost={'mana': '{1}'})]


register('Kitsune Mystic', _kitsune_mystic)
register('Autumn-Tail, Kitsune Sage', _autumn_tail)

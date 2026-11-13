from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _polukranos_unchained() -> list[AbilitySpec]:
    """Polukranos enters with six +1/+1 counters on it. It escapes with twelve +1/+1 counters on it instead.
    If damage would be dealt to Polukranos while it has a +1/+1 counter on it, prevent that damage and remove that many +1/+1 counters from it.
    {1}{B}{G}: Polukranos fights another target creature.
    Escape—{4}{B}{G}, Exile six other cards from your graveyard.
    """
    return [
        AbilitySpec('replacement', [EffectSpec('prevent_damage', {
            'to': 'self', 'amount': 'all',
            'rider': {'kind': 'remove_self_counter', 'counter': '+1/+1', 'scaled': True},
            'requires_counter': '+1/+1',
        })]),
        AbilitySpec('activated', [EffectSpec('fight', {'other_kind': 'creature', 'excludes_source': True})],
            cost={'text': '{1}{B}{G}'}),
    ]


register('Polukranos, Unchained', _polukranos_unchained,
    entry_counters={'is_x': False, 'count': 6, 'escape_count': 12, 'counter_type': '+1/+1'})

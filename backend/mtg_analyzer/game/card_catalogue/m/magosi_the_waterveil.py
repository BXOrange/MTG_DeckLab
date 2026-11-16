
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _magosi_the_waterveil() -> list[AbilitySpec]:
    "This land enters tapped.\n{T}: Add {U}.\n{U}, {T}: Put an eon counter on this land. Skip your next turn.\n{T}, Remove an eon counter from this land and return it to its owner's hand: Take an extra turn after this one."
    return [
        AbilitySpec(
            'activated',
            [EffectSpec('add_counters', {"count": 1, "kind": 'eon'}), EffectSpec('skip_next_step', {"step": 'turn'})],
            cost={"text": '{u}, {t}'},
            raw_text='{u}, {t}: put an eon counter on ~. skip your next turn.',
        ),
        AbilitySpec('activated', [EffectSpec('take_extra_turn', {'count': 1})],
                    cost={'taps_self': True, 'remove_counters': ['eon', 1], 'return_to_hand': 'self'}),
    ]


register('Magosi, the Waterveil', _magosi_the_waterveil)

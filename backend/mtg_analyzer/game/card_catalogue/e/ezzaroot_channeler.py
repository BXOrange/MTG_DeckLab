from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ezzaroot_channeler() -> list[AbilitySpec]:
    'Reach\nCreature spells you cast cost {X} less to cast, where X is the amount of life you gained this turn.\n{T}: You gain 2 life.'
    return [
        AbilitySpec(
            'activated',
            [EffectSpec('gain_life', {"amount": 2})],
            cost={"text": '{t}'},
            raw_text='{t}: you gain 2 life.',
        ),
        AbilitySpec(
            'static',
            [EffectSpec('cost_reduction', {"affects": 'your_spells', "spell_type": 'creature', "generic": 1, "per": 'life_gained_this_turn'})],
            raw_text='',
        ),
    ]


register('Ezzaroot Channeler', _ezzaroot_channeler)

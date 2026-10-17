from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _livio_oathsworn_sentinel() -> list[AbilitySpec]:
    """{1}{W}: Choose another target creature. Its controller may exile it with an aegis counter on it.
    {2}{W}, {T}: Return all exiled cards with aegis counters on them to the battlefield under their owners' control.
    Partner (You can have two commanders if both have partner.)
    """
    return [
        AbilitySpec('activated', [EffectSpec('pay_cost_then', {
            'cost': '', 'payer': 'target_controller',
            'effects': [{'type': 'exile', 'params': {
                'target_kind': 'other_creature', 'exile_counters': {'aegis': 1},
            }}],
        })], cost='{1}{W}'),
        AbilitySpec('activated', [EffectSpec('return_exile_counter_pool', {'counter': 'aegis'})],
                    cost='{2}{W}, {T}'),
        AbilitySpec('keyword', keyword={'name': 'Partner'}),
    ]


register('Livio, Oathsworn Sentinel', _livio_oathsworn_sentinel)

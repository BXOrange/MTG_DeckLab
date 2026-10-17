from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _niko_light_of_hope() -> list[AbilitySpec]:
    """When Niko enters, create two Shard tokens. (They're enchantments with "{2}, Sacrifice this token: Scry 1, then draw a card.")
    {2}, {T}: Exile target nonlegendary creature you control. Shards you control become copies of it until the next end step. Return it to the battlefield under its owner's control at the beginning of the next end step.
    """
    return [
        AbilitySpec('triggered', [EffectSpec('create_token', {'token_name': 'Shard', 'count': 2})],
                    trigger={'event': EventType.ENTERS_BATTLEFIELD, 'condition': {'subject': 'self'}}),
        AbilitySpec('activated', [EffectSpec('blink', {
            'target_kind': 'creature_you_control', 'creature_filter': {'nonlegendary': True},
            'departing_copy': {'recipients': 'you_control', 'filter': {'subtype': 'Shard'},
                               'duration': 'next_end_step'},
            'return_step': 'end',
        })], cost='{2}, {T}'),
    ]


register('Niko, Light of Hope', _niko_light_of_hope)

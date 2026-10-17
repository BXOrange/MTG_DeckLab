from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _realm_razer() -> list[AbilitySpec]:
    """When this creature enters, exile all lands.
    When this creature leaves the battlefield, return the exiled cards to the battlefield tapped under their owners' control.
    """
    return [
        AbilitySpec('triggered', [EffectSpec('exile', {
            'selector': 'all_lands', 'track_exiled_with': True,
        })], trigger={'event': EventType.ENTERS_BATTLEFIELD, 'condition': {'subject': 'self'}}),
        AbilitySpec('triggered', [EffectSpec('return_all_exiled_with', {'tapped': True})],
                    trigger={'event': EventType.LEAVES_BATTLEFIELD, 'condition': {'subject': 'self'}}),
    ]


register('Realm Razer', _realm_razer)

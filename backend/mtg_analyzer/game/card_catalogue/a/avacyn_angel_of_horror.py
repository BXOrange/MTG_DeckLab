from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _card() -> list[AbilitySpec]:
    # RULE 603.7: the next end step can belong to any player.
    def delayed():
        return [EffectSpec('create_delayed_trigger', {
            'step': 'end', 'scope': 'any', 'capture': 'trigger_subject',
            'trigger_event_key': 'instance_id',
            'effects': [{'type': 'return_captured_graveyard_card', 'params': {}}],
        })]

    return [
        AbilitySpec('triggered', delayed(),
                    trigger={'event': 'DIES', 'condition': {'subject': 'self'}}),
        AbilitySpec('triggered', delayed(), trigger={'event': 'DIES', 'condition': {
            'subject': 'group', 'controller': 'you', 'other': True,
            'filter': {'nontoken': True, 'card_type': 'creature'},
        }}),
    ]


register('Avacyn, Angel of Horror', _card)

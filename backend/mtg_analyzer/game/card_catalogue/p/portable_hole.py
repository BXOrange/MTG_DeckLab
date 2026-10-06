from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """
    When this artifact enters, exile target nonland permanent an opponent controls with mana
    value 2 or less until this artifact leaves the battlefield.

    Known limitation: this uses the legacy linked-exile leaves trigger. The return is
    respondable, and the enters trigger still exiles if the source left before resolution
    (rather than RULE 610.3).
    """
    return [
        AbilitySpec(
            'triggered',
            [
                EffectSpec(
                    'exile',
                    {
                        'target_kind': 'nonland_permanent_you_dont_control',
                        'max_mana_value': 2,
                        'remember': True,
                    },
                ),
            ],
            trigger={'event': EventType.ENTERS_BATTLEFIELD, 'condition': {'subject': 'self'}},
        ),
        AbilitySpec(
            'triggered',
            [EffectSpec('return_linked_exile', {})],
            trigger={'event': EventType.LEAVES_BATTLEFIELD, 'condition': {'subject': 'self'}},
        ),
    ]


register('Portable Hole', _specs)

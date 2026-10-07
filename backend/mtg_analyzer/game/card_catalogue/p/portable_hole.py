from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """
    When this artifact enters, exile target nonland permanent an opponent controls with mana
    value 2 or less until this artifact leaves the battlefield.

    RULE 610.3: immediate return, and no exile after the source has left.
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
                        'until_source_leaves': True,
                    },
                ),
            ],
            trigger={'event': EventType.ENTERS_BATTLEFIELD, 'condition': {'subject': 'self'}},
        ),
    ]


register('Portable Hole', _specs)

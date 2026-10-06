from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """Trample
    At the beginning of combat on your turn, choose one at random —
    • Other creatures you control get +3/+0 and gain trample until end of turn.
    • Discard your hand, then draw four cards.
    • Umaro deals 5 damage to any target.
    """
    return [
        AbilitySpec(
            'triggered',
            [],
            trigger={
                'event': EventType.STEP_BEGIN,
                'filter': {'step': 'begin_combat'},
                'phase_relation': 'you',
            },
            modes={
                'choose': 1,
                'random': True,
                'options': [
                    [
                        EffectSpec(
                            'pump',
                            {
                                'power': 3,
                                'toughness': 0,
                                'keywords': ['trample'],
                                'selector': 'other_creatures_you_control',
                            },
                        ),
                    ],
                    [EffectSpec('discard', {'whole_hand': True}), EffectSpec('draw', {'count': 4})],
                    [EffectSpec('damage', {'amount': 5, 'target_kind': 'any'})],
                ],
                'descriptions': ['Andere Kreaturen verstärken', 'Hand abwerfen und vier Karten ziehen', 'Fünf Schaden'],
            },
        ),
    ]


register('Umaro, Raging Yeti', _specs)

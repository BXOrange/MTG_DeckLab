from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """
    Choose three. You may choose the same mode more than once.
    • Target creature gets +3/-3 until end of turn.
    • Exile target nonland permanent, then return it to the battlefield tapped under its
    owner's control.
    • Create a 1/1 colorless Eldrazi Scion creature token with "Sacrifice this token: Add
    {C}."
    """
    return [
        AbilitySpec(
            'spell_effect',
            [],
            modes={
                'choose': 3,
                'repeatable': True,
                'options': [
                    [EffectSpec('pump', {'power': 3, 'toughness': -3, 'target_kind': 'creature'})],
                    [EffectSpec('blink', {'target_kind': 'nonland_permanent', 'tapped': True})],
                    [
                        EffectSpec(
                            'create_token',
                            {
                                'token_name': 'Eldrazi Scion',
                                'power': 1,
                                'toughness': 1,
                                'colors': [],
                                'subtypes': ['Eldrazi', 'Scion'],
                                'oracle_text': 'Sacrifice this token: Add {C}.',
                            },
                        ),
                    ],
                ],
                'descriptions': ['+3/-3', 'Exilieren und getappt zurückbringen', 'Eldrazi Scion erzeugen'],
            },
        ),
    ]


register('Eldrazi Confluence', _specs)

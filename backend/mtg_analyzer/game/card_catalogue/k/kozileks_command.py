from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _specs() -> list[AbilitySpec]:
    """
    Choose two —
    • Target player creates X 0/1 colorless Eldrazi Spawn creature tokens with "Sacrifice
    this token: Add {C}."
    • Target player scries X, then draws a card.
    • Exile target creature with mana value X or less.
    • Exile up to X target cards from graveyards.
    """
    return [
        AbilitySpec(
            'spell_effect',
            [],
            modes={
                'choose': 2,
                'options': [
                    [
                        EffectSpec(
                            'create_token',
                            {
                                'token_name': 'Eldrazi Spawn',
                                'count': 'x',
                                'creators': 'target',
                                'target_kind': 'player',
                                'power': 0,
                                'toughness': 1,
                                'colors': [],
                                'subtypes': ['Eldrazi', 'Spawn'],
                                'oracle_text': 'Sacrifice this token: Add {C}.',
                            },
                        ),
                    ],
                    [
                        EffectSpec('scry', {'count': 'x', 'target_kind': 'player'}),
                        EffectSpec(
                            'draw',
                            {'count': 1, 'player': {'of': 'previous_player', 'as': 'self'}},
                        ),
                    ],
                    [EffectSpec('exile', {'target_kind': 'creature', 'max_mana_value': 'x'})],
                    [
                        EffectSpec(
                            'exile',
                            {
                                'target_kind': 'any_graveyard_card',
                                'optional': True,
                                'count_selector': 'source_x_paid',
                            },
                        ),
                    ],
                ],
                'descriptions': [
                    'Eldrazi Spawn erzeugen',
                    'Hellsicht, dann ziehen',
                    'Kreatur exilieren',
                    'Friedhofskarten exilieren',
                ],
            },
        ),
    ]


register("Kozilek's Command", _specs)

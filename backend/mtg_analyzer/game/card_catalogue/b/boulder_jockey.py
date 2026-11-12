"""Boulder Jockey's land-drop costs and attacking Boulder."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _boulder_jockey():
    """({D} is a land drop. You may give up one potential land drop this turn to pay for {D}.)
Whenever Boulder Jockey attacks, you may pay {D}. If you do, create a 3/3 colorless Construct artifact creature token named Boulder that's tapped and attacking. Sacrifice that token at the beginning of the next end step."""
    return [
        AbilitySpec('spell_effect', [], additional_cost={'pay_land_drops': 1}),
        AbilitySpec('triggered', [EffectSpec('pay_cost_then', {
            'cost': '{D}', 'effects': [
                {'type': 'create_token', 'params': {'count': 1, 'token_name': 'Boulder',
                    'power': 3, 'toughness': 3, 'colors': [], 'subtypes': ['Construct'],
                    'is_artifact': True, 'tapped': True, 'attacking': True}},
                {'type': 'create_delayed_trigger', 'params': {'step': 'end', 'scope': 'any',
                    'capture': 'created_objects', 'description': 'Sacrifice the Boulder token.',
                    'effects': [{'type': 'sacrifice_specific', 'params': {'controlled_only': True}}]}},
            ],
        })], trigger={'event': EventType.ATTACKS, 'condition': {'subject': 'self'}}),
    ]


register('Boulder Jockey', _boulder_jockey)

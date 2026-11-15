"""Soulbond grants each member its own temporary combat copy."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mirage_phalanx():
    'Soulbond (You may pair this creature with another unpaired creature when either enters. They remain paired for as long as you control both of them.)\nAs long as Mirage Phalanx is paired with another creature, each of those creatures has "At the beginning of combat on your turn, create a token that\'s a copy of this creature, except it has haste and loses soulbond. Exile it at end of combat."'
    return [AbilitySpec('static', [EffectSpec('grant_triggered_ability', {
        'affects': 'soulbond_pair', 'trigger_event': EventType.STEP_BEGIN,
        'filter': {'step': 'begin_combat'}, 'phase_relation': 'you',
        'grant_effects': [
            {'type': 'copy_permanent', 'params': {'target_kind': None,
                'add_keywords': ['Haste'], 'remove_keywords': ['soulbond']}},
            {'type': 'create_delayed_trigger', 'params': {'step': 'end_combat', 'scope': 'any',
                'capture': 'created_objects', 'effects': [{'type': 'exile_specific', 'params': {}}],
                'description': 'Mirage Phalanx: Kampfkopie ins Exil'}},
        ],
    })])]


register('Mirage Phalanx', _mirage_phalanx)

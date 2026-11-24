"""The token's conditional end-step sacrifice is an intrinsic copy exception."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register, register_ability_line


SACRIFICE_LINE = "At the beginning of the end step, if you don't control a planeswalker, sacrifice this creature."


def _sacrifice_ability():
    condition = {'kind': 'control_count', 'selector': {
        'zone': 'battlefield', 'of': 'you', 'filter': {'card_type': 'planeswalker'},
    }, 'max': 0}
    return [AbilitySpec('triggered', [EffectSpec('sacrifice_self', {
        'require_source_incarnation': True,
    }, condition=condition)], trigger={'event': EventType.STEP_BEGIN, 'step': 'end',
        'active_if': condition}, raw_text=SACRIFICE_LINE)]


def _face_yourself():
    'For each creature target player controls, create a token that\'s a copy of that creature, except it has haste and "At the beginning of the end step, if you don\'t control a planeswalker, sacrifice this creature."'
    return [AbilitySpec('spell_effect', [EffectSpec('copy_player_creatures', {
        'ability_line': SACRIFICE_LINE,
    })])]


register_ability_line(SACRIFICE_LINE, _sacrifice_ability)
register('Face Yourself', _face_yourself)

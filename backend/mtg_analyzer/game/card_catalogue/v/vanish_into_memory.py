from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _vanish_into_memory():
    """Exile target creature. You draw cards equal to that creature's power. At the beginning of your next upkeep, return that card to the battlefield under its owner's control. If you do, discard cards equal to that creature's toughness."""
    return [AbilitySpec('spell_effect', [EffectSpec('bind', {
        'name': 'power', 'amount': {'kind': 'characteristic', 'of': 'target', 'characteristic': 'power'},
        'effects': [{'type': 'blink', 'params': {
            'target_kind': 'creature', 'return_step': 'upkeep', 'return_scope': 'controller',
            'exile_effects': [{'type': 'draw', 'params': {'count': '$power'}}],
            'return_if_successful': True,
            'return_effects': [{'type': 'bind', 'params': {
                'name': 'toughness', 'amount': {'kind': 'characteristic', 'of': 'previous_subject',
                                             'characteristic': 'toughness'},
                'effects': [{'type': 'discard', 'params': {'count': '$toughness'}}],
            }}],
        }}],
    })])]


register('Vanish into Memory', _vanish_into_memory)

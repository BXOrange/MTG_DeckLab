"""Firion creates a discounted Equipment copy with a one-shot upkeep sacrifice."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register, register_ability_line


DISCOUNT_LINE = "This Equipment's equip abilities cost {2} less to activate."


def _discount():
    return [AbilitySpec('static', [EffectSpec('cost_reduction', {
        'scope': 'activation', 'generic': 2, 'attach_kind': 'equip', 'self_only': True,
    })], raw_text=DISCOUNT_LINE)]


def _firion_wild_rose_warrior():
    'Equipped creatures you control have haste.\nWhenever a nontoken Equipment you control enters, create a token that\'s a copy of it, except it has "This Equipment\'s equip abilities cost {2} less to activate." Sacrifice that token at the beginning of the next upkeep.'
    return [AbilitySpec('static', [EffectSpec('grant_keyword', {
        'affects': {'zone': 'battlefield', 'of': 'you', 'filter': {'card_type': 'creature', 'equipped': True}}, 'keywords': ['haste'],
    })]), AbilitySpec('triggered', [
        EffectSpec('copy_permanent', {'target_kind': None, 'referent': 'trigger_event',
                                      'add_ability_lines': [DISCOUNT_LINE]}),
        EffectSpec('create_delayed_trigger', {'step': 'upkeep', 'scope': 'any', 'capture': 'created_objects',
            'effects': [{'type': 'sacrifice_specific', 'params': {'controlled_only': True}}],
            'description': 'Firion: Equipment-Kopie opfern'}),
    ], trigger={'event': EventType.ENTERS_BATTLEFIELD, 'condition': {
        'subject': 'group', 'controller': 'you', 'subtypes': ['equipment'], 'nontoken': True,
    }})]


register_ability_line(DISCOUNT_LINE, _discount)
register('Firion, Wild Rose Warrior', _firion_wild_rose_warrior)

"""Curie's copied draw ability uses base power, including later set effects."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register, register_ability_line


DRAW_LINE = "Whenever this creature deals combat damage to a player, draw cards equal to its base power."


def _draw():
    return [AbilitySpec('triggered', [EffectSpec('draw', {'count': {
        'kind': 'characteristic', 'of': 'source', 'characteristic': 'base_power',
    }})], trigger={'event': EventType.DAMAGE, 'condition': {'subject': 'self'},
                  'filter': {'combat': True, 'is_player': True}}, raw_text=DRAW_LINE)]


def _curie_emergent_intelligence():
    'Whenever Curie deals combat damage to a player, draw cards equal to its base power.\n{1}{U}, Exile another nontoken artifact creature you control: Curie becomes a copy of the exiled creature, except it has "Whenever this creature deals combat damage to a player, draw cards equal to its base power."'
    return [*_draw(), AbilitySpec('activated', [EffectSpec('become_copy_paid_exile', {
        'ability_line': DRAW_LINE,
    })], cost={'mana': '{1}{U}', 'exile_others': [1, 'other_nontoken_artifact_creature']})]


register_ability_line(DRAW_LINE, _draw)
register('Curie, Emergent Intelligence', _curie_emergent_intelligence)

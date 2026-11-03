"""PAR-226: flash permissions over shared spell filters (RULE 702.8, 601.3).

Standing ("you / any player may cast <filter> spells as though they had flash"), board-state conditional ("you may
cast this spell as though it had flash if <condition>") and one-shot temporary ("the next <type> spell you cast this
turn can be cast as though it had flash") forms, each parsed and then executed through `GameEngine.can_cast`.
"""
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.continuous import has_standing_flash_permission
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle


def engine():
    eng = GameEngine.new_game([('p1', 'Alice', []), ('p2', 'Bob', [])], starting_hand=0)
    eng.begin_turn()
    # Combat, not a main phase: only flash-speed casts are legal here (RULE 307.1 / 702.8a).
    eng.state.current_step = 'declare_attackers'
    return eng


def put(eng, name, type_line, text='', zone=Zone.BATTLEFIELD, owner='p1', **kw):
    card = Card(id=name, name=name, type_line=type_line, oracle_text=text, **kw)
    obj = GameObject(card, owner_id=owner, zone=zone)
    obj.controller_id = owner
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(obj)
    elif zone == Zone.HAND:
        eng.state.player_by_id(owner).add_to_zone(obj, Zone.HAND)
    return obj


def hand_spell(eng, name, type_line, text='', owner='p1', **kw):
    return put(eng, name, type_line, text, zone=Zone.HAND, owner=owner, **kw)


def standing_specs(text):
    specs = [s for a in parse_oracle(Card(id='x', name='X', type_line='Creature — Bear', oracle_text=text)).specs
             for s in a.effects]
    return {s.type: s.params for s in specs}


def test_standing_filters_parse_to_flash_permission():
    assert standing_specs('You may cast sorcery spells as though they had flash.')['flash_permission'] == {
        'type_filter': ['sorcery']}
    assert standing_specs('You may cast Dragon spells and artifact spells as though they had flash.')[
        'flash_permission'] == {'type_filter': ['dragon', 'artifact']}
    assert standing_specs('You may cast Aura and Equipment spells as though they had flash.')[
        'flash_permission'] == {'type_filter': ['aura', 'equipment']}
    assert standing_specs('Any player may cast Sliver spells as though they had flash.')['flash_permission'] == {
        'type_filter': ['sliver'], 'any_player': True}
    assert standing_specs('You may cast spells as though they had flash.')['flash_permission'] == {}


def test_unknown_filter_word_stays_unclaimed():
    assert 'flash_permission' not in standing_specs('You may cast frobnitz spells as though they had flash.')
    # A qualified phrase the permission cannot express fails closed rather than widening to every Aura.
    assert 'flash_permission' not in standing_specs(
        'You may cast Aura spells with enchant creature as though they had flash.')


def test_sorcery_filter_executes_for_controller_only():
    eng = engine()
    put(eng, 'Hypersonic Dragon', 'Creature — Dragon', 'You may cast sorcery spells as though they had flash.',
        is_creature=True, power=4, toughness=4)
    sorcery = hand_spell(eng, 'Shock Sorcery', 'Sorcery', is_sorcery=True)
    creature = hand_spell(eng, 'Bear', 'Creature — Bear', is_creature=True, power=2, toughness=2)
    p1 = eng.state.player_by_id('p1')
    assert has_standing_flash_permission(eng.state, p1, sorcery.card)
    assert not has_standing_flash_permission(eng.state, p1, creature.card)
    # RULE 702.8b: the permission is the controller's, an opponent's sorcery keeps sorcery timing.
    assert not has_standing_flash_permission(eng.state, eng.state.player_by_id('p2'), sorcery.card)


def test_any_player_permission_covers_opponent():
    eng = engine()
    put(eng, 'Quick Sliver', 'Creature — Sliver', 'Any player may cast Sliver spells as though they had flash.',
        is_creature=True, power=1, toughness=1)
    sliver = hand_spell(eng, 'Other Sliver', 'Creature — Sliver', is_creature=True, power=1, toughness=1, owner='p2')
    bear = hand_spell(eng, 'Bear', 'Creature — Bear', is_creature=True, power=2, toughness=2, owner='p2')
    p2 = eng.state.player_by_id('p2')
    assert has_standing_flash_permission(eng.state, p2, sliver.card)
    assert not has_standing_flash_permission(eng.state, p2, bear.card)


def test_historic_colorless_and_enchantment_words():
    eng = engine()
    put(eng, 'Renari', 'Creature — Human', 'You may cast historic spells and colorless spells and enchantment '
        'spells as though they had flash.', is_creature=True, power=1, toughness=1)
    p1 = eng.state.player_by_id('p1')
    legendary = Card(id='L', name='L', type_line='Legendary Creature — Elf', is_creature=True, is_legendary=True,
                     mana_cost_string='{G}')
    saga = Card(id='S', name='S', type_line='Enchantment — Saga', mana_cost_string='{1}{G}')
    colorless = Card(id='C', name='C', type_line='Instant', is_instant=True, mana_cost_string='{2}')
    green_instant = Card(id='G', name='G', type_line='Sorcery', is_sorcery=True, mana_cost_string='{G}')
    assert has_standing_flash_permission(eng.state, p1, legendary)
    assert has_standing_flash_permission(eng.state, p1, saga)
    assert has_standing_flash_permission(eng.state, p1, colorless)
    assert not has_standing_flash_permission(eng.state, p1, green_instant)


def conditional_flash_of(text, **kw):
    result = parse_oracle(Card(id='c', name='C', type_line=kw.pop('type_line', 'Creature — Bear'),
                               oracle_text=text, **kw))
    flashes = [a.conditional_flash for a in result.specs if a.conditional_flash]
    return result, flashes


def test_conditional_flash_forms_parse_to_active_if():
    for text in (
        'You may cast this spell as though it had flash if you control a Human.',
        'If you control a Human, you may cast this spell as though it had flash.',
        'As long as you control a Human, you may cast this spell as though it had flash.',
        'This spell has flash as long as you control a Human.',
    ):
        result, flashes = conditional_flash_of(text, is_creature=True)
        assert result.modeled, text
        assert flashes == [{'active_if': {
            'kind': 'control_count', 'min': 1,
            'selector': {'zone': 'battlefield', 'of': 'you', 'filter': {'subtype': 'human'}}}}], text


def test_conditional_flash_with_unparsed_condition_is_unclaimed():
    result, flashes = conditional_flash_of(
        'You may cast this spell as though it had flash if the moon is full.', is_creature=True)
    assert not result.modeled and not flashes


def test_conditional_flash_executes_against_board():
    eng = engine()
    spell = hand_spell(eng, 'Bard', 'Creature — Human',
                       'You may cast this spell as though it had flash if you control a Human.',
                       is_creature=True, power=2, toughness=2, mana_cost_string='{W}')
    p1 = eng.state.player_by_id('p1')
    p1.mana_pool.add('W', 1)
    assert not eng.can_cast(p1, spell)
    put(eng, 'Human Ally', 'Creature — Human', is_creature=True, power=1, toughness=1)
    assert eng.can_cast(p1, spell)


def test_target_condition_flash_photography():
    result, flashes = conditional_flash_of(
        'You may cast this spell as though it had flash if it targets a permanent you control.',
        type_line='Instant')
    assert flashes == [{'targets_a_permanent_you_control': True}]


def test_next_spell_grant_parses_and_is_consumed_by_the_cast():
    specs = match_clause('the next sorcery spell you cast this turn can be cast as though it had flash')
    assert [(s.type, s.params) for s in specs] == [('grant_flash_until_eot', {
        'next_only': True, 'card_types': ['sorcery']})]
    assert match_clause('the next frobnitz spell you cast this turn can be cast as though it had flash') is None

    eng = engine()
    source = put(eng, 'Quicken', 'Sorcery', is_sorcery=True)
    p1 = eng.state.player_by_id('p1')
    sorcery = hand_spell(eng, 'S1', 'Sorcery', is_sorcery=True, mana_cost_string='{R}')
    creature = hand_spell(eng, 'Bear', 'Creature — Bear', is_creature=True, power=2, toughness=2,
                          mana_cost_string='{R}')
    p1.mana_pool.add('R', 2)
    assert not eng.can_cast(p1, sorcery)
    for effect in build_effects(specs, source):
        effect.apply(GameContext(eng.state, eng.rules), None)
    assert eng.can_cast(p1, sorcery)
    assert not eng.can_cast(p1, creature)  # the grant is type-scoped, RULE 702.8b

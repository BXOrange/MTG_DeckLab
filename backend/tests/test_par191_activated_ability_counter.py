"""PAR-191: activated-only counter targets retain stack category and identity."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import legal_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.models.game.game_state import StackItem
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.spec import EffectSpec
from tests.test_mec118_opponent_choice import _db_card, _engine, _put


@pytest.mark.parametrize('name', ['Azorius Guildmage', 'Bind', 'Rimewind Cryomancer', 'Squelch', 'Voidmage Husher'])
def test_real_core_cards_are_modeled(name):
    assert parse_oracle(_db_card(name)).modeled


def test_shared_counter_row_keeps_broad_stifle_and_rejects_other_qualifiers():
    assert match_clause('counter target activated ability') == [
        EffectSpec('counter_ability', {'target_kind': 'activated_ability'})]
    assert match_clause('counter target activated or triggered ability') == [EffectSpec('counter_ability', {})]
    for text in ['counter target activated ability from an artifact source',
                 'counter target activated ability unless its controller pays {1}',
                 'counter target activated ability, triggered ability, or legendary spell']:
        assert match_clause(text) is None


def source_with_ability(eng):
    card = Card(id='Source', name='Source', type_line='Artifact',
                oracle_text='{T}: Draw a card.')
    source = _put(eng, card, 'p2')
    eng.activate_ability(eng.state.players[1], source)
    return source, eng.state.stack[-1]


def fund(eng):
    eng.state.players[0].mana_pool.add_many({'U': 10, 'W': 10, 'G': 10, 'C': 10})


@pytest.mark.parametrize('name', ['Bind', 'Squelch'])
@pytest.mark.parametrize('source_change', ['none', 'leaves', 'controller'])
def test_actual_spell_counters_opponent_activation_and_controller_draws(name, source_change):
    eng = _engine(); p, q = eng.state.players
    source, activation = source_with_ability(eng)
    draw = _put(eng, Card(id='Draw', name='Draw', type_line='Instant', is_instant=True), 'p1', Zone.HAND)
    p.hand.remove(draw); draw.zone = Zone.LIBRARY; p.library.append(draw)
    spell = _put(eng, _db_card(name), 'p1', Zone.HAND)
    if source_change == 'leaves':
        eng.rules.put_into_graveyard(source)
    elif source_change == 'controller':
        source.controller_id = 'p1'
    fund(eng)
    eng.cast_spell(p, spell, targets=[activation])
    eng.resolve_until_stable()
    assert draw in p.hand and not q.hand
    assert (source in eng.state.battlefield) is (source_change != 'leaves')
    assert spell in p.graveyard and activation not in eng.state.stack


def test_normal_guildmage_action_offers_only_activated_items_and_counters():
    eng = _engine(); p, q = eng.state.players
    source, activation = source_with_ability(eng)
    trigger = StackItem(kind='ability', controller_id='p2', source=source, category='triggered_ability')
    eng.state.stack.append(trigger)
    spell_obj = _put(eng, Card(id='Spell', name='Spell', type_line='Instant', is_instant=True), 'p2')
    spell = StackItem(kind='spell', controller_id='p2', obj=spell_obj)
    eng.state.stack.append(spell)
    guildmage = _put(eng, _db_card('Azorius Guildmage'), 'p1')
    fund(eng)
    action = next(a for a in eng.legal_actions(p) if a['type'] == 'activate_ability'
                  and a['instance_id'] == guildmage.instance_id and a['ability_index'] == 1)
    assert not action.get('locked')
    assert {o['stack_id'] for o in action['targets'][0]['options']} == {activation.stack_id}
    eng.activate_ability(p, guildmage, 1, targets=[activation])
    eng.rules.resolve_top_of_stack()
    assert activation not in eng.state.stack and trigger in eng.state.stack and spell in eng.state.stack


@pytest.mark.parametrize('category', ['triggered_ability', 'spell'])
def test_announcement_rejects_nonactivated_stack_categories_without_paying(category):
    eng = _engine(); p, q = eng.state.players
    source, activation = source_with_ability(eng)
    wrong = StackItem(kind='spell' if category == 'spell' else 'ability', controller_id='p2',
                      category=category, source=source if category != 'spell' else None,
                      obj=source if category == 'spell' else None)
    eng.state.stack.append(wrong)
    bind = _put(eng, _db_card('Bind'), 'p1', Zone.HAND)
    fund(eng); before = p.mana_pool.total()
    eng.state._physical_cast_validation = True
    with pytest.raises(ValueError):
        eng.cast_spell(p, bind, targets=[wrong if category != 'spell' else source])
    assert p.mana_pool.total() == before


def test_removed_stack_target_fizzles_draw_rider_and_does_not_counter_replacement():
    eng = _engine(); p, q = eng.state.players
    source, activation = source_with_ability(eng)
    bind = _put(eng, _db_card('Bind'), 'p1', Zone.HAND)
    fund(eng); eng.cast_spell(p, bind, targets=[activation])
    eng.state.stack.remove(activation)
    replacement = StackItem(kind='ability', controller_id='p2', source=source,
                            category='activated_ability')
    eng.state.stack.insert(0, replacement)
    eng.rules.resolve_top_of_stack()
    assert replacement in eng.state.stack and not p.hand
    assert not p.has_lost  # The draw did not resolve against an empty library.


def test_cloned_counter_removes_exact_activation_and_preserves_other_same_source():
    eng = _engine(); p, q = eng.state.players
    source, activation = source_with_ability(eng)
    other = StackItem(kind='ability', controller_id='p2', source=source, category='activated_ability')
    eng.state.stack.append(other)
    bind = _put(eng, _db_card('Bind'), 'p1', Zone.HAND)
    fund(eng); eng.cast_spell(p, bind, targets=[activation])
    restored = GameEngine(eng.state.clone())
    restored.rules.resolve_top_of_stack()
    assert activation.stack_id not in {i.stack_id for i in restored.state.stack}
    assert other.stack_id in {i.stack_id for i in restored.state.stack}
    assert activation in eng.state.stack


def test_mana_ability_resolves_immediately_and_has_no_counter_target():
    eng = _engine(); p, q = eng.state.players
    island = _put(eng, Card(id='Island', name='Island', type_line='Basic Land — Island', is_land=True), 'p2')
    eng.tap_for_mana(q, island)
    assert q.mana_pool.total() == 1 and not eng.state.stack
    bind = _put(eng, _db_card('Bind'), 'p1', Zone.HAND)
    assert legal_targets(eng.state, p.id, bind.spell_effects[0].target_spec, source=bind) == []


def test_activated_counter_runtime_refuses_triggered_item_even_if_passed_directly():
    eng = _engine(); p, q = eng.state.players
    source, activation = source_with_ability(eng)
    activation.category = 'triggered_ability'
    bind = _put(eng, _db_card('Bind'), 'p1', Zone.HAND)
    bind.spell_effects[0].apply(GameContext(eng.state, eng.rules), [activation])
    assert activation in eng.state.stack


def test_physical_stifle_cast_still_accepts_triggered_ability():
    eng = _engine(); p, q = eng.state.players
    source, activation = source_with_ability(eng)
    trigger = StackItem(kind='ability', controller_id='p2', source=source, category='triggered_ability')
    eng.state.stack.append(trigger)
    stifle = _put(eng, _db_card('Stifle'), 'p1', Zone.HAND)
    fund(eng); eng.state._physical_cast_validation = True
    eng.cast_spell(p, stifle, targets=[trigger])
    eng.rules.resolve_top_of_stack()
    assert trigger not in eng.state.stack and activation in eng.state.stack


def test_new_category_is_revalidated_before_a_draw_rider_resolves():
    eng = _engine(); p, q = eng.state.players
    source, activation = source_with_ability(eng)
    bind = _put(eng, _db_card('Bind'), 'p1', Zone.HAND)
    fund(eng); eng.cast_spell(p, bind, targets=[activation])
    # The category is immutable in ordinary play; exercising it also proves
    # resolution uses the narrowed requirement rather than presence alone.
    activation.category = 'triggered_ability'
    eng.rules.resolve_top_of_stack()
    assert activation in eng.state.stack and not p.has_lost


@pytest.mark.parametrize('clone', [False, True])
@pytest.mark.parametrize('remove_target', [False, True])
def test_husher_cast_and_entry_trigger_offer_only_the_activation(clone, remove_target):
    eng = _engine(); p, q = eng.state.players
    source, activation = source_with_ability(eng)
    trigger = StackItem(kind='ability', controller_id='p2', source=source, category='triggered_ability')
    eng.state.stack.append(trigger)
    husher = _put(eng, _db_card('Voidmage Husher'), 'p1', Zone.HAND)
    fund(eng); eng.cast_spell(p, husher)
    eng.rules.resolve_top_of_stack()
    eng.rules.put_triggers_on_stack()
    if clone:
        eng = GameEngine(eng.state.clone())
    if eng.state.pending_choice is not None:
        choice = eng.state.pending_choice
        assert {o['stack_id'] for o in choice['options'] if 'stack_id' in o} == {activation.stack_id}
        if remove_target:
            eng.state.stack[:] = [i for i in eng.state.stack if i.stack_id != activation.stack_id]
        eng.rules.resolve_choice(next(o['id'] for o in choice['options'] if o.get('stack_id') == activation.stack_id))
    if not remove_target:
        eng.rules.resolve_top_of_stack()
    ids = {i.stack_id for i in eng.state.stack}
    assert activation.stack_id not in ids and trigger.stack_id in ids
    assert eng.state.find_object(husher.instance_id) in eng.state.battlefield


def test_shared_trigger_choice_distinguishes_stack_and_card_ids():
    eng = _engine(); p, q = eng.state.players
    source, activation = source_with_ability(eng)
    broad = _put(eng, _db_card('Voidmage Husher'), 'p1')
    ability = broad.triggered_abilities[0]
    # A spell/card id can numerically equal a distinct ability stack id.
    options = [{'instance_id': activation.stack_id, 'name': 'Spell'},
               {'stack_id': activation.stack_id, 'name': 'Ability'},
               {'player_id': 'p2', 'name': 'Player'}]
    choice = eng.rules._trigger_target_choice(ability, options)
    assert len({o['id'] for o in choice['options']}) == 3
    assert eng.rules._resolve_choice_option(choice['options'], f'stack:{activation.stack_id}') is activation
    assert eng.rules._resolve_choice_option(choice['options'], 'p2') is q


def test_rimewind_requires_four_snow_permanents_before_activation():
    eng = _engine(); p, q = eng.state.players
    source, activation = source_with_ability(eng)
    rimewind = _put(eng, _db_card('Rimewind Cryomancer'), 'p1')
    rimewind.summoning_sick = False
    fund(eng)
    with pytest.raises(ValueError):
        eng.activate_ability(p, rimewind, targets=[activation])
    for index in range(4):
        _put(eng, Card(id=f'Snow{index}', name=f'Snow{index}', type_line='Snow Artifact'), 'p1')
    eng.activate_ability(p, rimewind, targets=[activation])
    eng.rules.resolve_top_of_stack()
    assert activation not in eng.state.stack and rimewind.tapped


@pytest.mark.parametrize('union', [False, True])
def test_shared_broad_entry_trigger_chooses_triggered_ability_and_preserves_spells(union):
    eng = _engine(); p, q = eng.state.players
    source, activation = source_with_ability(eng)
    trigger = StackItem(kind='ability', controller_id='p2', source=source, category='triggered_ability')
    eng.state.stack.append(trigger)
    spell_obj = _put(eng, Card(id='Spell', name='Spell', type_line='Instant', is_instant=True), 'p2')
    spell_obj.zone = Zone.STACK
    spell = StackItem(kind='spell', controller_id='p2', obj=spell_obj)
    eng.state.stack.append(spell)
    text = ('Counter target spell, activated ability, or triggered ability.' if union
            else 'Counter target activated or triggered ability.')
    creature = _put(eng, Card(id='Counter creature', name='Counter creature', type_line='Creature',
                              is_creature=True, power=2, toughness=2, mana_cost_string='{U}', keywords=['Flash'],
                              oracle_text='Flash\nWhen this creature enters, ' + text), 'p1', Zone.HAND)
    fund(eng); eng.cast_spell(p, creature)
    eng.rules.resolve_top_of_stack(); eng.rules.put_triggers_on_stack()
    choice = eng.state.pending_choice
    assert {o['stack_id'] for o in choice['options'] if 'stack_id' in o} == {activation.stack_id, trigger.stack_id}
    assert (any(o.get('instance_id') == spell_obj.instance_id for o in choice['options'])) is union
    eng.rules.resolve_choice(next(o['id'] for o in choice['options'] if o.get('stack_id') == trigger.stack_id))
    eng.rules.resolve_top_of_stack()
    assert trigger not in eng.state.stack and activation in eng.state.stack and spell in eng.state.stack

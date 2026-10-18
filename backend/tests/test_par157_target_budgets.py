"""Aggregate target limits are shared by casts, triggers and copies."""
import pytest

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from test_mec106_gift import _engine, _bf, _creature, _hand
from test_par157_back_selections import _cached


def _dead(eng, name, mv, owner='p1', oracle=''):
    obj = _bf(eng, Card(id=name, name=name, type_line='Creature — Bear', is_creature=True,
        power=2, toughness=2, converted_mana_cost=mv, oracle_text=oracle), owner)
    eng.rules.put_into_graveyard(obj)
    return obj


def _phoenix(eng):
    card = _cached("Joshua, Phoenix's Dominant // Phoenix, Warden of Fire")
    assert parse_oracle(card).modeled and parse_oracle(card.back_face()).modeled
    source = _bf(eng, card)
    eng.resolve_until_stable()
    player = eng.state.player_by_id('p1')
    player.mana_pool.add_many({'C': 3, 'R': 1, 'W': 1})
    eng.activate_ability(player, source, 0)
    eng.resolve_until_stable()
    assert source.transformed and source.name == card.back_name
    eng.rules.advance_sagas(player)
    eng.resolve_until_stable()
    eng.rules.advance_sagas(player)
    eng.resolve_until_stable()
    return source


@pytest.mark.full_cache
def test_joshua_front_back_targets_share_budget_before_resolution_and_clone_independently():
    eng = _engine()
    two, four, five, seven, zero = [_dead(eng, f'MV{n}', n) for n in [2, 4, 5, 7, 0]]
    other = _dead(eng, 'Opponent', 1, 'p2')
    source = _phoenix(eng)
    assert eng.state.pending_choice
    offered = {o['id'] for o in eng.state.pending_choice['options']}
    assert str(seven.instance_id) not in offered and str(other.instance_id) not in offered
    eng.resolve_pending_choice(str(two.instance_id))
    assert two.zone == four.zone == Zone.GRAVEYARD and source.transformed
    offered = {o['id'] for o in eng.state.pending_choice['options']}
    assert str(four.instance_id) in offered and str(zero.instance_id) in offered
    assert str(five.instance_id) not in offered and str(two.instance_id) not in offered
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice(str(four.instance_id))
    clone.rules.resolve_choice('stop')
    assert clone.state.stack and not clone.state.pending_choice
    clone.resolve_until_stable()
    assert clone.state.find_object(two.instance_id).zone == Zone.BATTLEFIELD
    assert clone.state.find_object(four.instance_id).zone == Zone.BATTLEFIELD
    assert clone.state.find_object(source.instance_id).transformed is False
    assert two.zone == four.zone == Zone.GRAVEYARD and source.transformed


@pytest.mark.full_cache
@pytest.mark.parametrize('pool', [[], [7], [2]])
def test_joshua_may_choose_zero_targets_and_still_return_front(pool):
    eng = _engine()
    victims = [_dead(eng, str(n), n) for n in pool]
    source = _phoenix(eng)
    if eng.state.pending_choice:
        choice = eng.state.pending_choice
        stop = next(o['id'] for o in choice['options'] if o['id'] in {'stop', 'decline'})
        eng.resolve_pending_choice(stop)
    eng.resolve_until_stable()
    assert source.zone == Zone.BATTLEFIELD and not source.transformed
    assert all(v.zone == Zone.GRAVEYARD for v in victims)


@pytest.mark.parametrize('measure,field', [('mana value','total_mana_value_max'),('power','total_power_max')])
@pytest.mark.parametrize('quant', ['any number of', 'up to 3', '2 or 3'])
def test_return_count_scope_measure_and_subtype_axes_recombine(measure, field, quant):
    specs = parse_effect_body(f'return {quant} target ally creature cards with total {measure} 6 or less '
        "from an opponent's graveyard to your hand")
    assert specs and specs[0].params[field] == 6
    assert specs[0].params['target_kind'] == 'opponent_graveyard_creature'
    assert specs[0].params['destination'] == 'hand' and specs[0].params['subtype'] == 'Ally'


@pytest.mark.parametrize('text', [
    'return any number of target imaginary creature cards with total mana value 6 or less from your graveyard to the battlefield',
    'return any number of target creature cards with total mana value 6 exactly from your graveyard to the battlefield',
    'return any number of target creature cards with total loyalty 6 or less from your graveyard to the battlefield',
])
def test_unknown_aggregate_shapes_fail_closed(text):
    assert parse_effect_body(text) is None


def test_spell_cast_rejects_combined_over_budget_and_allows_a_partial_legal_return():
    eng = _engine()
    two, four, five = [_dead(eng, str(n), n) for n in [2, 4, 5]]
    spell = _hand(eng, Card(id='Return', name='Budget Return', type_line='Sorcery', is_sorcery=True,
        oracle_text='Return any number of target creature cards with total mana value 6 or less from your graveyard to the battlefield.'))
    player = eng.state.player_by_id('p1')
    with pytest.raises(ValueError, match='limit'):
        eng.cast_spell(player, spell, targets=[two, five])
    eng.cast_spell(player, spell, targets=[two, four])
    eng.rules.exile(four)
    eng.resolve_until_stable()
    assert two.zone == Zone.BATTLEFIELD and four.zone == Zone.EXILE


@pytest.mark.full_cache
def test_joshua_return_batch_waits_for_each_entry_choice_before_blink_and_survives_clone():
    eng = _engine()
    two = _dead(eng, 'First entrant', 2, oracle='As this creature enters, choose a color.')
    four = _dead(eng, 'Second entrant', 4, oracle='As this creature enters, choose a color.')
    source = _phoenix(eng)
    eng.resolve_pending_choice(str(two.instance_id))
    eng.resolve_pending_choice(str(four.instance_id))
    assert eng.state.pending_choice and source.transformed
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice(clone.state.pending_choice['options'][0]['id'])
    assert clone.state.pending_choice
    assert clone.state.find_object(two.instance_id).zone == Zone.GRAVEYARD
    assert clone.state.find_object(four.instance_id).zone == Zone.GRAVEYARD
    clone.resolve_pending_choice(clone.state.pending_choice['options'][0]['id'])
    clone.resolve_until_stable()
    for obj in [two, four]:
        returned = clone.state.find_object(obj.instance_id)
        assert returned.zone == Zone.BATTLEFIELD and returned.chosen_color
    assert not clone.state.find_object(source.instance_id).transformed
    assert two.zone == four.zone == Zone.GRAVEYARD and source.transformed


def test_copied_mana_budget_applies_to_the_whole_changed_target_set():
    eng = _engine()
    cards = [_dead(eng, f'Copy MV{n}', n) for n in [2, 4, 5, 1]]
    spell = _hand(eng, Card(id='copy return', name='Copy Return', type_line='Sorcery', is_sorcery=True,
        oracle_text='Return any number of target creature cards with total mana value 6 or less from your graveyard to the battlefield.'))
    original = eng.cast_spell(eng.state.player_by_id('p1'), spell, targets=cards[:2])
    copied = eng.rules.copy_spell(original, 'p1', choose_new_targets=True)[0]
    options = eng.state.pending_choice['options']
    eng.rules.resolve_choice(next(o['id'] for o in options if o.get('instance_id') == cards[2].instance_id))
    options = eng.state.pending_choice['options']
    assert cards[1].instance_id not in {o.get('instance_id') for o in options}
    eng.rules.resolve_choice(next(o['id'] for o in options if o.get('instance_id') == cards[3].instance_id))
    assert copied.targets == cards[2:] and original.targets == cards[:2]


def test_fixed_count_and_activated_budgets_fail_before_paying_and_export_limits():
    eng = _engine()
    two, five = [_dead(eng, f'Limit MV{n}', n) for n in [2, 5]]
    text = 'Return up to three target creature cards with total mana value 6 or less from your graveyard to the battlefield.'
    spell = _hand(eng, Card(id='fixed return', name='Fixed Return', type_line='Sorcery', is_sorcery=True, oracle_text=text))
    player = eng.state.player_by_id('p1')
    with pytest.raises(ValueError, match='limit'):
        eng.cast_spell(player, spell, targets=[two, five])
    source = _bf(eng, Card(id='activation', name='Activation Source', type_line='Enchantment',
        oracle_text='{1}: Return any number of target creature cards with total mana value 6 or less from your graveyard to the battlefield.'))
    player.mana_pool.add('C', 1)
    requirements = eng._ability_target_requirements(player, source.activated_abilities[0], source)
    assert requirements[0]['any_number'] and requirements[0]['total_mana_value_max'] == 6
    assert {o['mana_value'] for o in requirements[0]['options']} == {2, 5}
    with pytest.raises(ValueError, match='limit'):
        eng.activate_ability(player, source, 0, targets=[two, five])
    assert player.mana_pool.total() == 1


@pytest.mark.full_cache
def test_any_number_has_no_fixed_cap_even_for_zero_mana_cards():
    eng = _engine()
    cards = [_dead(eng, f'Zero {n}', 0) for n in range(20)]
    source = _phoenix(eng)
    for obj in cards:
        eng.rules.resolve_choice(str(obj.instance_id))
    eng.resolve_until_stable()
    assert all(obj.zone == Zone.BATTLEFIELD for obj in cards)
    assert not source.transformed


@pytest.mark.full_cache
@pytest.mark.parametrize('all_illegal', [False, True])
def test_aggregate_target_group_rejects_later_graveyard_visits_and_all_illegal_stops_blink(all_illegal):
    eng = _engine()
    two, four = [_dead(eng, f'Visit {n}', n) for n in [2, 4]]
    source = _phoenix(eng)
    eng.rules.resolve_choice(str(two.instance_id))
    eng.rules.resolve_choice(str(four.instance_id))
    for obj in [two, four] if all_illegal else [two]:
        eng.rules.return_from_graveyard(obj, 'hand')
        eng.rules.put_into_graveyard(obj)
    eng.resolve_until_stable()
    assert two.zone == Zone.GRAVEYARD
    if all_illegal:
        assert four.zone == source.zone == Zone.GRAVEYARD
    else:
        assert four.zone == source.zone == Zone.BATTLEFIELD and not source.transformed


def test_aggregate_return_reuses_entry_counter_tapped_and_control_axes():
    from mtg_analyzer.parser.oracle.spec import EffectSpec
    eng = _engine()
    cards = [_dead(eng, f'Entry {n}', n, 'p2') for n in [2, 4]]
    source = _bf(eng, _creature('Return source'))
    effect = build_effects([EffectSpec('return_from_graveyard', {
        'target_kind': 'any_graveyard_creature', 'any_number': True,
        'total_mana_value_max': 6, 'under_your_control': True,
        'tapped': True, 'extra_counters': {'kind': '+1/+1', 'count': 2}, 'haste': True,
    })], source)[0]
    effect.apply(eng.rules.context, cards)
    eng.resolve_until_stable()
    for obj in cards:
        assert obj.zone == Zone.BATTLEFIELD and obj.tapped and obj.controller_id == 'p1'
        assert obj.counters.get('+1/+1') == 2 and 'haste' in obj.granted_keywords


@pytest.mark.full_cache
def test_wondrous_revival_uses_the_same_entry_batch_without_an_aggregate_limit():
    eng = _engine()
    eng.state.interactive_ordering = True
    cards = [_dead(eng, f'Entering Hero {i}', 1, oracle='As this creature enters, choose a color.')
             for i in [1, 2]]
    for obj in cards:
        obj.card.type_line = 'Creature — Hero'
    spell = _hand(eng, _cached('Wondrous Revival'))
    player = eng.state.player_by_id('p1')
    player.mana_pool.add_many({'W': 5, 'C': 10})
    eng.cast_spell(player, spell, targets=cards)
    eng.resolve_until_stable()
    assert eng.state.pending_choice
    eng.resolve_pending_choice(eng.state.pending_choice['options'][0]['id'])
    assert eng.state.pending_choice and all(obj.zone == Zone.GRAVEYARD for obj in cards)
    eng.resolve_pending_choice(eng.state.pending_choice['options'][0]['id'])
    eng.resolve_until_stable()
    assert all(obj.zone == Zone.BATTLEFIELD and obj.chosen_color for obj in cards)


@pytest.mark.parametrize('kind', ['spell', 'activation', 'trigger'])
def test_aggregate_power_is_rechecked_for_every_announcement_path(kind):
    from mtg_analyzer.models.game.events import EventType, GameEvent
    eng = _engine()
    cards = [_dead(eng, f'Growing power {i}', 1) for i in [1, 2]]
    body = ('Return up to three target creature cards with total power 6 or less '
            'from your graveyard to the battlefield. You gain 3 life.')
    player = eng.state.player_by_id('p1')
    if kind == 'spell':
        source = _hand(eng, Card(id='power check', name='Changing Power', type_line='Sorcery',
            is_sorcery=True, oracle_text=body))
        eng.cast_spell(player, source, targets=cards)
    elif kind == 'activation':
        source = _bf(eng, Card(id='power check', name='Changing Power', type_line='Enchantment',
            oracle_text='{0}: ' + body))
        eng.activate_ability(player, source, 0, targets=cards)
    else:
        source = _bf(eng, Card(id='power check', name='Changing Power', type_line='Enchantment',
            oracle_text='At the beginning of your upkeep, ' + body))
        eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='upkeep', phase='beginning'))
        eng.resolve_until_stable()
        for obj in cards:
            eng.rules.resolve_choice(str(obj.instance_id))
    cards[0].card.power = 5
    eng.resolve_until_stable()
    assert all(obj.zone == Zone.GRAVEYARD for obj in cards)
    assert player.life == 20
    if kind == 'spell':
        assert source.zone == Zone.GRAVEYARD

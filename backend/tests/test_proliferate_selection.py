"""RULE 701.34a: recipient choice, repeated actions, and suspended riders."""
import pytest

from mtg_analyzer.game.effects.core import ProliferateEffect, _apply_effects_partitioned
from mtg_analyzer.game.effects.counters_tokens import PhaseOutProliferatedEffect
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.models.game.events import EventType
from tests.test_modal_creature_filter_family import _rules, _bf, _creature, _card


def start(rules, times=1, source=None):
    ProliferateEffect(times=times, source=source).apply(rules.context)


def pick(rules, obj):
    rules.resolve_choice(f'object:{obj.instance_id}')


def test_selection_is_staged_non_targeted_and_all_kinds_travel_together():
    rules, state, own, enemy = _rules()
    a = _bf(state, _creature('Mine'))
    b = _bf(state, _creature('Theirs'), 'p2')
    a.counters.update({'+1/+1': 2, 'stun': 1})
    b.counters['+1/+1'] = 1
    enemy.poison = 2
    start(rules)
    pick(rules, a)
    assert a.counters == {'+1/+1': 2, 'stun': 1}
    assert not state.stack  # selecting isn't targeting / committing a crime
    rules.resolve_choice(None)
    assert a.counters == {'+1/+1': 3, 'stun': 2}
    assert b.counters['+1/+1'] == 1 and enemy.poison == 2


def test_player_selection_includes_all_player_counter_types():
    rules, state, own, enemy = _rules()
    own.counters['energy'] = 3
    enemy.poison = 4
    enemy.counters.update({'rad': 2, 'experience': 1})
    start(rules)
    rules.resolve_choice('player:p2')
    assert enemy.poison == 4  # staged while the own-player option remains
    rules.resolve_choice(None)
    assert enemy.poison == 5
    assert enemy.counters == {'rad': 3, 'experience': 2}
    assert own.counters['energy'] == 3


def test_repeat_reopens_independent_selection_and_decline_still_proliferates():
    rules, state, own, enemy = _rules()
    a = _bf(state, _creature('A'))
    b = _bf(state, _creature('B'))
    a.counters['+1/+1'] = b.counters['+1/+1'] = 1
    events = []
    state.subscribe(lambda e: events.append(e.type))
    start(rules, times=2)
    pick(rules, a)
    rules.resolve_choice(None)
    assert state.pending_choice['remaining'] == 1
    rules.resolve_choice(None)
    assert a.counters['+1/+1'] == 2 and b.counters['+1/+1'] == 1
    assert events.count(EventType.PROLIFERATED) == 2


def test_no_counters_and_exiled_or_phased_permanents_are_not_offered():
    rules, state, own, enemy = _rules()
    a = _bf(state, _creature('Phased'))
    a.counters['charge'] = 1
    a.phased_out = True
    events = []
    state.subscribe(lambda e: events.append(e.type))
    start(rules, times=2)
    assert state.pending_choice is None
    assert a.counters['charge'] == 1
    assert events.count(EventType.PROLIFERATED) == 2


def test_invalid_or_duplicate_answers_do_not_finish_or_add_counters():
    rules, state, own, enemy = _rules()
    a = _bf(state, _creature('A')); a.counters['+1/+1'] = 1
    enemy.poison = 1
    start(rules)
    pick(rules, a)
    with pytest.raises(ValueError):
        pick(rules, a)
    assert state.pending_choice and a.counters['+1/+1'] == 1
    rules.resolve_choice(None)
    assert a.counters['+1/+1'] == 2


def test_clone_resumes_picks_and_phase_out_receipt_without_original_references():
    rules, state, own, enemy = _rules()
    source = _bf(state, _card('Source', '', 'Artifact'))
    a = _bf(state, _creature('A')); a.counters['+1/+1'] = 1
    b = _bf(state, _creature('B')); b.counters['+1/+1'] = 1
    _apply_effects_partitioned([ProliferateEffect(source=source),
                               PhaseOutProliferatedEffect(source=source)], rules.context, [], None)
    pick(rules, a)
    cloned = state.clone()
    restored = RulesEngine(cloned)
    restored.resolve_choice(None)
    assert restored.resume_deferred_effects()
    choice = cloned.pending_choice
    assert choice['kind'] == 'choose_objects'
    assert {o.get('instance_id') for o in choice['options'] if o.get('instance_id')} == {a.instance_id}
    restored.resolve_choice(str(a.instance_id))
    assert cloned.find_object(a.instance_id).phased_out
    assert not a.phased_out and a.counters['+1/+1'] == 1
    assert cloned.find_object(b.instance_id).counters['+1/+1'] == 1


def test_atomic_selection_validation_and_empty_confirmation():
    rules, state, own, enemy = _rules()
    a = _bf(state, _creature('A')); a.counters['+1/+1'] = 1
    start(rules)
    with pytest.raises(ValueError):
        rules.resolve_choice(['object:'+str(a.instance_id)] * 2)
    assert a.counters['+1/+1'] == 1 and state.pending_choice
    rules.resolve_choice([])
    assert a.counters['+1/+1'] == 1 and state.pending_choice is None


def test_human_recommendation_uses_smart2_but_accepts_edits_atomically():
    from tests.services.test_bots import make_game, keep
    from mtg_analyzer.services.bot_policies.smart2 import SmartBot2
    from mtg_analyzer.services.game_session import GameActionError
    session = make_game()
    keep(session, 'ann', 'bob')
    state = session.engine.state
    a = _bf(state, _creature('Own counter creature'), 'ann'); a.counters['+1/+1'] = 1
    b = _bf(state, _creature('Enemy counter creature'), 'bob'); b.counters['+1/+1'] = 1
    state.player_by_id('ann').poison = 9
    state.player_by_id('bob').poison = 1
    start(session.engine.rules, times=2)
    v = session.view(perspective='ann')
    pending = v['pending_choice']
    recommended = pending['recommended_ids']
    assert set(recommended) == {f'object:{a.instance_id}', 'player:bob'}
    bot = SmartBot2('ann')
    bot.prepare(session)
    action = bot.answer_choice(v, session.legal_actions('ann'))
    assert action['option_id'] in recommended
    assert session.view(perspective='bob')['pending_choice'] is None
    # Edits are accepted even when deliberately worse than the recommendation.
    session.apply_action({'type':'choose','selection_id':pending['selection_id'],
                          'option_ids':[f'object:{b.instance_id}']}, actor_id='ann')
    assert a.counters['+1/+1'] == 1 and b.counters['+1/+1'] == 2
    assert state.player_by_id('ann').poison == 9 and state.player_by_id('bob').poison == 1
    next_pending = session.view(perspective='ann')['pending_choice']
    assert next_pending['selection_id'] != pending['selection_id']
    with pytest.raises(GameActionError):
        session.apply_action({'type':'choose','selection_id':pending['selection_id'],'option_ids':[]}, actor_id='ann')
    session.apply_action({'type':'choose','selection_id':next_pending['selection_id'],'option_ids':[]}, actor_id='ann')
    assert session.engine.state.pending_choice is None


def test_replacement_order_pauses_before_next_proliferation_and_survives_clone():
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    rules, state, own, enemy = _rules()
    for name in ['Doubling Season', 'Doubling Season']:
        bind_from_catalogue(_bf(state, _card(name, '', 'Enchantment')))
    a = _bf(state, _creature('A')); a.counters['+1/+1'] = 1
    start(rules, times=2)
    rules.resolve_choice([f'object:{a.instance_id}'])
    assert state.pending_choice['kind'] == 'replacement_order'
    assert a.counters['+1/+1'] == 1
    cloned = state.clone()
    restored = RulesEngine(cloned)
    restored.resolve_choice(cloned.pending_choice['options'][0]['id'])
    assert cloned.find_object(a.instance_id).counters['+1/+1'] in (4, 5)
    assert a.counters['+1/+1'] == 1
    assert restored.resume_deferred_effects()
    assert cloned.pending_choice['kind'] == 'proliferate'
    assert cloned.pending_choice['remaining'] == 1
    restored.resolve_choice([])
    assert cloned.pending_choice is None

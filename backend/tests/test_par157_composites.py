"""Printed-order and repeated-visit regressions for compound flickers."""
import pytest

from mtg_analyzer.game.effects.flicker_composites import (
    AcrobaticsEffect, AnotherRoundEffect,
)
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.models.game.events import EventType
from test_mec106_gift import _engine, _bf, _creature, _hand, _spell


def _answer(eng, answer):
    eng.rules.resolve_choice(str(answer))


def test_another_round_fresh_set_each_pass_and_all_exiles_before_returns():
    eng = _engine()
    a = _bf(eng, _creature('A'))
    b = _bf(eng, _creature('B'))
    enemy = _bf(eng, _creature('Enemy'), player='p2')
    spell = _hand(eng, _spell('Another Round', '', 'Sorcery'))
    spell.x_paid = 1
    events = []
    original = eng.state.fire_event
    def observe(event):
        if event.type in (EventType.LEAVES_BATTLEFIELD, EventType.ENTERS_BATTLEFIELD):
            events.append(event.type)
        return original(event)
    eng.state.fire_event = observe
    AnotherRoundEffect(spell).apply(eng.rules.context)
    assert str(enemy.instance_id) not in [o['id'] for o in eng.state.pending_choice['options']]
    _answer(eng, a.instance_id)
    _answer(eng, b.instance_id)
    assert a.zone == b.zone == Zone.BATTLEFIELD
    assert events == []  # Selection is complete before any movement.
    _answer(eng, 'done')
    assert events == [EventType.LEAVES_BATTLEFIELD] * 2 + [EventType.ENTERS_BATTLEFIELD] * 2
    a_visit, b_visit = a.zone_incarnation, b.zone_incarnation
    _answer(eng, b.instance_id)
    _answer(eng, 'done')
    assert eng.state.pending_choice is None
    assert a.zone_incarnation == a_visit
    assert b.zone_incarnation > b_visit


def test_another_round_zero_x_still_one_optional_pass_and_zero_selected():
    eng = _engine()
    creature = _bf(eng, _creature('A'))
    source = _hand(eng, _spell('Another Round', '', 'Sorcery'))
    before = creature.zone_incarnation
    AnotherRoundEffect(source).apply(eng.rules.context)
    _answer(eng, 'done')
    assert creature.zone_incarnation == before
    assert eng.state.pending_choice is None


def test_another_round_cannot_return_tokens_or_keep_stolen_creature():
    eng = _engine()
    token = _bf(eng, _creature('Token'))
    token.is_token = True
    stolen = _bf(eng, _creature('Stolen'), player='p2')
    stolen.controller_id = 'p1'
    source = _hand(eng, _spell('Another Round', '', 'Sorcery'))
    source.x_paid = 1
    AnotherRoundEffect(source).apply(eng.rules.context)
    _answer(eng, token.instance_id)
    _answer(eng, stolen.instance_id)
    _answer(eng, 'done')
    assert token.zone == Zone.EXILE
    assert stolen.zone == Zone.BATTLEFIELD and stolen.controller_id == 'p2'
    assert eng.state.pending_choice is None  # No creatures remain under p1 control.


@pytest.mark.parametrize('roll, expected_visits', [(1, 1), (9, 1), (10, 3), (20, 3)])
def test_acrobatics_rolls_after_exile_then_tracks_new_exile_visits(roll, expected_visits):
    eng = _engine()
    a = _bf(eng, _creature('A'))
    b = _bf(eng, _creature('B'))
    token = _bf(eng, _creature('Token'))
    token.is_token = True
    enemy = _bf(eng, _creature('Enemy'), player='p2')
    source = _hand(eng, _spell("Lae'zel's Acrobatics", ''))
    initial = a.zone_incarnation
    def random_int(sides):
        assert sides == 20
        assert a.zone == b.zone == Zone.EXILE
        assert token.zone == enemy.zone == Zone.BATTLEFIELD
        return roll - 1
    eng.rules.random_int = random_int
    AcrobaticsEffect(source).apply(eng.rules.context)
    assert a.zone == b.zone == Zone.EXILE
    assert a.zone_incarnation == initial + expected_visits
    assert len(eng.state.delayed_triggers) == 1
    delayed = eng.state.delayed_triggers[0]
    assert delayed.step == 'end' and delayed.scope == 'any'
    delayed.effects[0].apply(eng.rules.context)
    assert a.zone == b.zone == Zone.BATTLEFIELD
    assert token.zone == enemy.zone == Zone.BATTLEFIELD


def test_acrobatics_delayed_return_never_returns_new_exile_stay():
    eng = _engine()
    a = _bf(eng, _creature('A'))
    source = _hand(eng, _spell("Lae'zel's Acrobatics", ''))
    eng.rules.random_int = lambda sides: 0
    AcrobaticsEffect(source).apply(eng.rules.context)
    effect = eng.state.delayed_triggers[0].effects[0]
    eng.rules.return_from_exile(a, a.zone_incarnation)
    eng.rules.exile(a)
    effect.apply(eng.rules.context)
    assert a.zone == Zone.EXILE


def test_round_selection_is_clone_safe():
    eng = _engine()
    a = _bf(eng, _creature('A'))
    source = _hand(eng, _spell('Another Round', '', 'Sorcery'))
    AnotherRoundEffect(source).apply(eng.rules.context)
    _answer(eng, a.instance_id)
    cloned = eng.state.clone()
    from mtg_analyzer.game.rules_engine import RulesEngine
    rules = RulesEngine(cloned)
    rules.resolve_choice('done')
    assert cloned.find_object(a.instance_id).zone_incarnation > a.zone_incarnation
    assert eng.state.pending_choice is not None


def test_acrobatics_reuses_interactive_ignore_one_and_survives_clone():
    eng = _engine()
    from test_mec117_ignore_one import _put, OTHER_THUMB
    _put(eng, "Krark's Other Thumb", OTHER_THUMB)
    a = _bf(eng, _creature('A'))
    source = _hand(eng, _spell("Lae'zel's Acrobatics", ''))
    rolls = iter([19, 0])
    eng.rules.random_int = lambda sides: next(rolls)
    eng.state.interactive_roll_picks = True
    AcrobaticsEffect(source).apply(eng.rules.context)
    pending = eng.state.pending_choice
    assert pending['kind'] == 'choose_die_group'
    assert a.zone == Zone.EXILE
    assert eng.state.delayed_triggers == []
    cloned = eng.state.clone()
    from mtg_analyzer.game.rules_engine import RulesEngine
    rules = RulesEngine(cloned)
    low = next(o['id'] for o in cloned.pending_choice['options'] if o['label'] == '1')
    rules.resolve_choice(low)
    rules.resume_deferred_effects()
    actual = cloned.find_object(a.instance_id)
    assert actual.zone == Zone.EXILE
    assert len(cloned.delayed_triggers) == 1
    assert actual.zone_incarnation == a.zone_incarnation  # Low row never returns immediately.
    assert eng.state.pending_choice is not None


def test_authored_another_round_real_cast_and_choice_resolves_into_graveyard():
    eng = _engine()
    a = _bf(eng, _creature('A'))
    source = _hand(eng, _spell('Another Round', "Exile any number of creatures you control, then return them to the battlefield under their owner's control. Then repeat this process X more times.", 'Sorcery'))
    p1 = eng.state.player_by_id('p1')
    p1.mana_pool.add('C', 10)
    eng.cast_spell(p1, source, x=1)
    eng.resolve_until_stable()
    assert eng.state.pending_choice['kind'] == 'flicker_round_selection'
    start = a.zone_incarnation
    for _ in range(2):
        _answer(eng, a.instance_id)
        _answer(eng, 'done')
        eng.resolve_until_stable()
    assert a.zone_incarnation == start + 4
    assert source.zone == Zone.GRAVEYARD
    assert not eng.state.deferred_effects


def test_authored_acrobatics_real_cast_and_actual_delayed_stack():
    eng = _engine()
    a = _bf(eng, _creature('A'))
    text = "Exile all nontoken creatures you control, then roll a d20.\n1—9 | Return those cards to the battlefield under their owner's control at the beginning of the next end step.\n10—20 | Return those cards to the battlefield under their owner's control, then exile them again. Return those cards to the battlefield under their owner's control at the beginning of the next end step."
    source = _hand(eng, _spell("Lae'zel's Acrobatics", text))
    p1 = eng.state.player_by_id('p1')
    p1.mana_pool.add('C', 10)
    eng.rules.random_int = lambda sides: 19
    eng.cast_spell(p1, source)
    eng.resolve_until_stable()
    assert source.zone == Zone.GRAVEYARD
    assert a.zone == Zone.EXILE
    eng._fire_delayed_triggers('end')
    assert len(eng.state.stack) == 1
    eng.resolve_until_stable()
    assert a.zone == Zone.BATTLEFIELD
    assert not eng.state.delayed_triggers

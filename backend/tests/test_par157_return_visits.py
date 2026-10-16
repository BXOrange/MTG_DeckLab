"""A flicker returns its captured exile visit, never a later object visit."""
import pytest
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.effects.choices_actions import ReturnSpecificToBattlefieldEffect
from mtg_analyzer.models.game.game_object import Zone
from test_par136_delayed_blink import _engine, _bf, _card, _cast, _end_step

ORACLE = "Exile target creature. Return that card to the battlefield under its owner's control at the beginning of the next end step."


@pytest.mark.parametrize('revisit', [False, True])
def test_actual_delayed_flicker_only_returns_original_exile_visit(revisit):
    eng, player = _engine()
    victim = _bf(eng, _card('Victim'))
    _cast(eng, player, ORACLE, [victim])
    assert victim.zone == Zone.EXILE
    if revisit:
        eng.rules.return_to_hand(victim)
        eng.rules.exile(victim)
    _end_step(eng)
    assert victim.zone == (Zone.EXILE if revisit else Zone.BATTLEFIELD)


def test_captured_return_visit_survives_clone_without_mutating_original():
    eng, player = _engine()
    victim = _bf(eng, _card('Victim'))
    _cast(eng, player, ORACLE, [victim])
    clone = GameEngine(eng.state.clone())
    _end_step(clone)
    assert clone.state.find_object(victim.instance_id).zone == Zone.BATTLEFIELD
    assert victim.zone == Zone.EXILE


def test_captured_return_rejects_later_exile_visit_in_cloned_state():
    eng, player = _engine()
    victim = _bf(eng, _card('Victim'))
    _cast(eng, player, ORACLE, [victim])
    clone = GameEngine(eng.state.clone())
    current = clone.state.find_object(victim.instance_id)
    clone.rules.return_to_hand(current); clone.rules.exile(current)
    _end_step(clone)
    assert current.zone == Zone.EXILE
    _end_step(eng)
    assert victim.zone == Zone.BATTLEFIELD


def test_immediate_blink_token_never_returns_even_before_sba():
    eng, player = _engine()
    token = _bf(eng, _card('Token'))
    token.is_token = True
    eng.rules.blink(token)
    assert token not in eng.state.battlefield


def test_captured_token_never_returns_even_before_sba():
    eng, player = _engine()
    token = _bf(eng, _card('Token'))
    token.is_token = True
    eng.rules.exile(token)
    effect = ReturnSpecificToBattlefieldEffect([token])
    effect.apply(eng.rules.context)
    assert token not in eng.state.battlefield


def test_immediate_blink_rejects_changed_exile_visit(monkeypatch):
    eng, player = _engine()
    victim = _bf(eng, _card('Victim'))
    original_exile = eng.rules.exile
    def changed_visit(obj):
        original_exile(obj)
        eng.rules.return_to_hand(obj)
        original_exile(obj)
    monkeypatch.setattr(eng.rules, 'exile', changed_visit)
    eng.rules.blink(victim)
    assert victim.zone == Zone.EXILE and victim not in eng.state.battlefield


@pytest.mark.parametrize('when', ['before_original_resolves', 'after_original_resolves'])
def test_marchesa_never_returns_a_later_graveyard_visit(when):
    from test_delayed_trigger_examples import _engine as engine, _marchesa, _battlefield_obj
    eng = engine('p1', 'p2')
    _marchesa(eng.state)
    victim = _battlefield_obj(eng.state, _card('Marchesa Pawn'), 'p1')
    victim.counters['+1/+1'] = 1
    eng.rules.put_into_graveyard(victim)
    assert eng.rules.put_triggers_on_stack() == 1
    if when == 'after_original_resolves':
        eng.resolve_until_stable()
        assert len(eng.state.delayed_triggers) == 1
    eng.rules.return_to_hand(victim)
    eng.rules.put_into_graveyard(victim)
    if when == 'before_original_resolves':
        eng.resolve_until_stable()
    _end_step(eng)
    assert victim.zone == Zone.GRAVEYARD


@pytest.mark.parametrize('when_stolen', ['before_original_resolves', 'after_original_resolves'])
def test_marchesa_delayed_return_controller_is_original_ability_controller(when_stolen):
    from test_delayed_trigger_examples import _engine as engine, _marchesa, _battlefield_obj
    eng = engine('p1', 'p2')
    marchesa = _marchesa(eng.state)
    victim = _battlefield_obj(eng.state, _card('Borrowed Pawn'), 'p2')
    victim.controller_id = 'p1'
    victim.counters['+1/+1'] = 1
    eng.rules.put_into_graveyard(victim)
    assert eng.rules.put_triggers_on_stack() == 1
    if when_stolen == 'before_original_resolves':
        marchesa.controller_id = 'p2'
    eng.resolve_until_stable()
    assert len(eng.state.delayed_triggers) == 1
    assert eng.state.delayed_triggers[0].controller_id == 'p1'
    if when_stolen == 'after_original_resolves':
        marchesa.controller_id = 'p2'
    _end_step(eng)
    assert victim.zone == Zone.BATTLEFIELD and victim.controller_id == 'p1'
    assert victim.owner_id == 'p2'


def test_marchesa_token_dies_and_cannot_return_at_end_step():
    from test_delayed_trigger_examples import _engine as engine, _marchesa, _battlefield_obj
    eng = engine('p1', 'p2')
    _marchesa(eng.state)
    token = _battlefield_obj(eng.state, _card('Countered token'), 'p1')
    token.is_token = True
    token.counters['+1/+1'] = 1
    eng.rules.put_into_graveyard(token)
    eng.resolve_until_stable()
    _end_step(eng)
    assert token not in eng.state.battlefield
    assert token not in eng.state.player_by_id('p1').graveyard


def test_marchesa_graveyard_visit_capture_survives_clone():
    from test_delayed_trigger_examples import _engine as engine, _marchesa, _battlefield_obj
    eng = engine('p1', 'p2')
    _marchesa(eng.state)
    victim = _battlefield_obj(eng.state, _card('Countered pawn'), 'p1')
    victim.counters['+1/+1'] = 1
    eng.rules.put_into_graveyard(victim)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    clone = GameEngine(eng.state.clone())
    cloned = clone.state.find_object(victim.instance_id)
    clone.rules.return_to_hand(cloned); clone.rules.put_into_graveyard(cloned)
    _end_step(clone)
    assert cloned.zone == Zone.GRAVEYARD
    _end_step(eng)
    assert victim.zone == Zone.BATTLEFIELD

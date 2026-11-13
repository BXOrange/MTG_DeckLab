"""Astral Drift's self-cycling and battlefield-only cycling blink."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, RICH
from tests.support.star_trek import advance_to


def _board(zone=Zone.BATTLEFIELD):
    engine=game(players=3,library=30)
    advance_to(engine,'main1')
    source=card(engine,'Astral Drift',zone=zone)
    target=filler(engine,'Target',player='p2',power=2,toughness=3)
    return engine,source,target


def _cycle(engine,obj,player='p1'):
    p=engine.state.player_by_id(player)
    p.mana_pool.add_many(RICH)
    engine.activate_ability(p,obj,0)
    engine.resolve_until_stable()


def _answer(engine,target=None,accept=True):
    for _ in range(8):
        choice=engine.state.pending_choice
        if choice is None:
            return
        options=choice['options']
        if not accept and any(o['id'] in ('decline','no','skip') for o in options):
            pick=next(o['id'] for o in options if o['id'] in ('decline','no','skip'))
        elif any(o.get('instance_id')==getattr(target,'instance_id',None) for o in options):
            option=next(o for o in options if o.get('instance_id')==target.instance_id)
            pick=option['id']
        else:
            pick='yes' if accept else 'no'
            if not any(o['id']==pick for o in options):
                pick=options[0 if accept else -1]['id']
        engine.resolve_pending_choice(pick)
        engine.resolve_until_stable()
    raise AssertionError('Unfinished cycling choice')


def test_fresh_specs_binding_and_native_cycling():
    engine,source,target=_board(Zone.HAND)
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(source.triggered_abilities)==2 and len(source.activated_abilities)==1


@pytest.mark.parametrize('self_cycle',[False,True])
def test_cycling_exiles_any_creature_then_returns_under_owner_control(self_cycle):
    engine,source,target=_board(Zone.HAND if self_cycle else Zone.BATTLEFIELD)
    target.controller_id='p1'
    cycled=source if self_cycle else card(engine,'Drifting Meadow',zone=Zone.HAND)
    before=len(engine.state.player_by_id('p1').hand)
    _cycle(engine,cycled)
    _answer(engine,target)
    assert target.zone==Zone.EXILE
    assert cycled.zone==Zone.GRAVEYARD
    assert len(engine.state.player_by_id('p1').hand)==before
    advance_to(engine,'end')
    engine.resolve_until_stable()
    assert target.zone==Zone.BATTLEFIELD and target.controller_id=='p2'


@pytest.mark.parametrize('zone',[Zone.HAND,Zone.GRAVEYARD,Zone.EXILE])
def test_other_cards_do_not_trigger_drift_outside_battlefield(zone):
    engine,source,target=_board(zone)
    cycled=card(engine,'Drifting Meadow',zone=Zone.HAND)
    _cycle(engine,cycled)
    assert engine.state.pending_choice is None and target.zone==Zone.BATTLEFIELD


def test_opponents_cycle_does_not_trigger():
    engine,source,target=_board()
    cycled=card(engine,'Drifting Meadow',player='p2',zone=Zone.HAND)
    _cycle(engine,cycled,player='p2')
    assert engine.state.pending_choice is None and target.zone==Zone.BATTLEFIELD


def test_declining_exile_still_draws_for_cycling():
    engine,source,target=_board(Zone.HAND)
    _cycle(engine,source)
    _answer(engine,target,accept=False)
    assert target.zone==Zone.BATTLEFIELD and source.zone==Zone.GRAVEYARD


def test_return_survives_source_removal_and_state_clone():
    engine,source,target=_board()
    cycled=card(engine,'Drifting Meadow',zone=Zone.HAND)
    _cycle(engine,cycled)
    _answer(engine,target)
    assert target.zone==Zone.EXILE
    engine.rules.exile(source)
    engine=GameEngine(engine.state.clone())
    target=engine.state.find_object(target.instance_id)
    advance_to(engine,'end')
    engine.resolve_until_stable()
    assert target.zone==Zone.BATTLEFIELD


def test_return_does_not_follow_new_exile_visit():
    engine,source,target=_board()
    _cycle(engine,card(engine,'Drifting Meadow',zone=Zone.HAND))
    _answer(engine,target)
    engine.rules.return_from_graveyard(target,'battlefield')
    engine.rules.exile(target)
    advance_to(engine,'end')
    engine.resolve_until_stable()
    assert target.zone==Zone.EXILE


def test_self_cycling_triggers_even_if_discard_is_replaced_by_exile():
    engine,source,target=_board(Zone.HAND)
    card(engine,'Rest in Peace')
    _cycle(engine,source)
    assert source.zone==Zone.EXILE
    _answer(engine,target)
    assert target.zone==Zone.EXILE


def test_cycling_during_end_step_returns_at_the_following_end_step():
    engine,source,target=_board()
    cycled=card(engine,'Drifting Meadow',zone=Zone.HAND)
    advance_to(engine,'end')
    _cycle(engine,cycled)
    _answer(engine,target)
    assert target.zone==Zone.EXILE
    engine.advance_step()
    engine.resolve_until_stable()
    assert target.zone==Zone.EXILE
    advance_to(engine,'end')
    engine.resolve_until_stable()
    assert target.zone==Zone.BATTLEFIELD


def test_battlefield_trigger_follows_current_controller():
    engine,source,target=_board()
    source.controller_id='p2'
    _cycle(engine,card(engine,'Drifting Meadow',player='p2',zone=Zone.HAND),player='p2')
    _answer(engine,target)
    assert target.zone==Zone.EXILE


def test_normal_discard_is_not_cycling():
    engine,source,target=_board(Zone.HAND)
    engine.rules.discard_specific(source)
    engine.resolve_until_stable()
    assert target.zone==Zone.BATTLEFIELD and engine.state.pending_choice is None

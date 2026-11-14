"""Bounty checks begun extra turns, not queued turns or per-turn counters."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, RICH
from tests.support.star_trek import advance_to


NAME='H.M.S. Bounty, Unlikely Timeship'


def board(charge=8,whale=True):
    engine=game(players=3,library=30); advance_to(engine,'main1')
    ship=card(engine,NAME)
    if charge:
        engine.rules.add_counters(ship,charge,'charge')
    body=filler(engine,'Whale',type_line='Creature — Whale',power=2,toughness=2) if whale else None
    engine.recompute_continuous_effects()
    return engine,ship,body,engine.state.player_by_id('p1')


def hit(engine,ship,target='p2',combat_damage=True):
    engine.rules.deal_damage(engine.state.player_by_id(target),1,source=ship,combat=combat_damage)
    engine.resolve_until_stable()


def test_fresh_specs_station_and_threshold():
    engine,ship,body,player=board(0)
    a,b=specs_for(ship.card),specs_for(ship.card)
    assert a[0] is not b[0] and a[3].effects[0] is not b[3].effects[0]
    assert ship.activated_abilities and not combat.has(ship,'flying')
    engine.rules.add_counters(ship,8,'charge'); engine.recompute_continuous_effects()
    assert combat.has(ship,'flying') and ship.is_creature
    assert (ship.power,ship.toughness)==(3,4)


def test_station_activation_uses_real_creature_power():
    engine,ship,body,player=board(0)
    crew=filler(engine,'Station crew',power=8,toughness=8)
    player.mana_pool.add_many(RICH)
    engine.activate_ability(player,ship,0,tap_choices=[crew.instance_id]); engine.resolve_until_stable()
    assert crew.tapped and ship.counters.get('charge')==8
    assert ship.is_creature and combat.has(ship,'flying')


def test_combat_damage_draws_and_queues_extra_turn_with_whale():
    engine,ship,body,player=board(); before=len(player.hand)
    hit(engine,ship)
    assert len(player.hand)==before+1 and engine.state.extra_turns==['p1']
    assert not engine.state.players_begun_extra_turn


def test_multiple_hits_can_queue_multiple_turns_before_one_begins():
    engine,ship,body,player=board()
    hit(engine,ship); hit(engine,ship)
    assert engine.state.extra_turns==['p1','p1']
    engine.begin_turn()
    assert engine.state.active_player.id=='p1' and engine.state.players_begun_extra_turn=={'p1'}
    engine.state.extra_turns.clear()
    before=len(player.hand); hit(engine,ship)
    assert len(player.hand)==before+1 and not engine.state.extra_turns


def test_without_whale_still_draws_but_does_not_queue_extra_turn():
    engine,ship,body,player=board(whale=False); before=len(player.hand)
    hit(engine,ship)
    assert len(player.hand)==before+1 and not engine.state.extra_turns


@pytest.mark.parametrize('charge,combat_damage',[(7,True),(8,False)])
def test_only_charged_combat_damage_to_player_triggers(charge,combat_damage):
    engine,ship,body,player=board(charge); before=len(player.hand)
    hit(engine,ship,combat_damage=combat_damage)
    assert len(player.hand)==before and not engine.state.extra_turns


def test_damage_to_creature_does_not_trigger():
    engine,ship,body,player=board(); before=len(player.hand)
    engine.rules.deal_damage(body,1,source=ship,combat=True); engine.resolve_until_stable()
    assert len(player.hand)==before and not engine.state.extra_turns


def test_whale_condition_is_checked_at_resolution():
    engine,ship,body,player=board()
    engine.rules.deal_damage(engine.state.player_by_id('p2'),1,source=ship,combat=True)
    engine.rules.exile(body); engine.resolve_until_stable()
    assert not engine.state.extra_turns


def test_other_players_extra_turn_does_not_block_yours():
    engine,ship,body,player=board()
    engine.state.extra_turns.append('p2'); engine.begin_turn()
    assert engine.state.players_begun_extra_turn=={'p2'}
    hit(engine,ship)
    assert engine.state.extra_turns==['p1']


def test_skipped_extra_turn_was_not_begun():
    engine,ship,body,player=board()
    card(engine,'Stranglehold',player='p2')
    engine.state.extra_turns.append('p1'); engine.begin_turn()
    assert engine.state.active_player.id=='p2' and not engine.state.players_begun_extra_turn


def test_clone_preserves_history_after_bounty_leaves_and_returns():
    engine,ship,body,player=board()
    engine.state.extra_turns.append('p1'); engine.begin_turn()
    clone=GameEngine(engine.state.clone())
    copied=clone.state.find_object(ship.instance_id)
    clone.rules.exile(copied); clone.rules.return_from_graveyard(copied,'battlefield')
    clone.rules.add_counters(copied,8,'charge'); clone.recompute_continuous_effects()
    hit(clone,copied)
    assert clone.state.players_begun_extra_turn=={'p1'} and not clone.state.extra_turns



def test_real_cast_optional_whale_search():
    engine,ship,body,player=board(0)
    engine.rules.return_to_hand(ship)
    whale=filler(engine,'Library Whale',type_line='Creature — Whale',power=2,toughness=2,zone=Zone.LIBRARY)
    player.mana_pool.add_many(RICH)
    engine.cast_spell(player,ship); engine.resolve_until_stable()
    engine.resolve_pending_choice('do')
    choice=engine.state.pending_choice
    option=next(o for o in choice['options'] if o.get('instance_id')==whale.instance_id)
    engine.resolve_pending_choice(str(option['id']))
    assert whale.zone==Zone.HAND and ship.zone==Zone.BATTLEFIELD


def test_optional_search_can_be_declined():
    engine,ship,body,player=board(0)
    engine.rules.return_to_hand(ship)
    player.mana_pool.add_many(RICH)
    before=list(player.library)
    engine.cast_spell(player,ship); engine.resolve_until_stable()
    engine.resolve_pending_choice('decline')
    assert player.library==before and ship.zone==Zone.BATTLEFIELD


def test_history_survives_later_normal_turns():
    engine,ship,body,player=board()
    engine.state.extra_turns.append('p1'); engine.begin_turn(); engine.begin_turn()
    assert engine.state.active_player.id=='p2'
    hit(engine,ship)
    assert engine.state.players_begun_extra_turn=={'p1'} and not engine.state.extra_turns


def test_changed_controller_uses_their_own_extra_turn_history():
    engine,ship,body,player=board()
    engine.state.extra_turns.append('p1'); engine.begin_turn()
    ship.controller_id='p2'; body.controller_id='p2'; engine.recompute_continuous_effects()
    hit(engine,ship,target='p3')
    assert engine.state.extra_turns==['p2']

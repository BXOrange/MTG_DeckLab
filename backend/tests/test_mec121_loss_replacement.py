"""Loss replacement executes ordered recovery and survives interactive snapshots."""
import pytest
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext, ReplacementEffect, _apply_effects_partitioned
from mtg_analyzer.game.effects.life_sacrifice import GainLifeEffect
from mtg_analyzer.game.effects.game_status import WinConditionEffect
from mtg_analyzer.game.effects.choices_actions import LoseGameEffect
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause

BODY='If you would lose the game, instead your life total becomes 20, shuffle your graveyard into your library, you lose all poison counters, and you lose this emblem.'
ORACLE='Flying, indestructible\nWhen Puresteel Angel enters, exile all artifacts that aren\'t colorless.\nWhenever Puresteel Angel deals combat damage to a player, you get an emblem with "'+BODY+'"'

def engine(n=2):
    eng=GameEngine.new_game([(f'p{i+1}',f'P{i+1}',[]) for i in range(n)],starting_hand=0)
    eng.state.current_step='main1'
    return eng

def obj(eng,name='Source',owner='p1',zone=Zone.BATTLEFIELD,**kwargs):
    card=Card(id=name,name=name,type_line=kwargs.pop('type_line','Enchantment'),**kwargs)
    o=GameObject(card,owner_id=owner,zone=zone);bind_from_catalogue(o)
    if zone==Zone.BATTLEFIELD:eng.state.add_to_battlefield(o)
    else:eng.state.player_by_id(owner).add_to_zone(o,zone)
    return o

def emblem(eng,owner='p1'):
    src=obj(eng,owner=owner)
    specs=match_clause('you get an emblem with "'+BODY.lower()+'"')
    assert specs
    for effect in build_effects(specs,source=src):effect.apply(GameContext(eng.state,eng.rules))
    eng.rules.exile(src)
    return eng.state.player_by_id(owner).emblems[-1]

def answer(eng,index=0):
    eng.resolve_pending_choice(str(index))
    eng.resolve_until_stable()

@pytest.mark.parametrize('reason',['life','poison','draw_from_empty','commander_damage','effect'])
def test_no_emblem_losses_remain_terminal(reason):
    eng=engine();p=eng.state.players[0]
    if reason=='effect':eng.rules._player_loses(p,reason)
    else:
        if reason=='life':p.life=0
        if reason=='poison':p.poison=10
        if reason=='draw_from_empty':eng.rules.draw(p,1)
        if reason=='commander_damage':p.commander_damage['cmd']={'amount':21}
        eng.rules.check_state_based_actions()
    assert p.has_lost and p.loss_reason==reason and eng.state.game_over
    assert sum(e.type==EventType.PLAYER_LOST for e in eng.state.event_log)==1

@pytest.mark.parametrize('reason',['life','poison','draw_from_empty','effect'])
def test_real_emblem_replaces_loss_and_preserves_unmentioned_state(reason):
    eng=engine();p=eng.state.players[0];em=emblem(eng)
    dead=obj(eng,'Grave',zone=Zone.GRAVEYARD);hand=obj(eng,'Hand',zone=Zone.HAND)
    board=obj(eng,'Untouched');p.counters['energy']=4
    if reason=='life':p.life=-3
    if reason=='poison':p.poison=12
    if reason=='draw_from_empty':eng.rules.draw(p,1)
    if reason=='effect':eng.rules._player_loses(p,reason)
    else:eng.rules.check_state_based_actions()
    assert not p.has_lost and p.loss_reason is None and p.life==20 and p.poison==0
    assert dead in p.library and not p.graveyard and hand in p.hand and board in eng.state.battlefield
    assert p.counters['energy']==4 and em not in p.emblems and not eng.state.game_over
    assert any(e.type==EventType.SHUFFLE for e in eng.state.event_log)


def test_two_emblems_choose_one_and_simultaneous_same_player_losses_are_one_event():
    eng=engine();p=eng.state.players[0];first=emblem(eng);second=emblem(eng)
    p.life=0;p.poison=10;eng.rules.draw(p,1)
    eng.rules.check_state_based_actions()
    assert eng.state.pending_choice['kind']=='replacement_order'
    assert eng.state.pending_choice['player_id']=='p1' and len(eng.state.pending_choice['options'])==2
    assert not p.has_lost and not eng.state.game_over
    answer(eng,1)
    assert p.emblems==[first] and second not in p.emblems and p.life==20 and p.poison==0
    assert not p.attempted_draw_from_empty and not p.has_lost


def test_simultaneous_losers_all_lose_instead_of_first_loss_awarding_victory():
    eng=engine(3)
    for p in eng.state.players:p.life=0
    eng.rules.check_state_based_actions()
    assert all(p.has_lost for p in eng.state.players)
    assert eng.state.game_over and eng.state.winner_id is None


def test_simultaneous_replacements_are_serialized_apnap_and_do_not_end_game_early():
    eng=engine();p,q=eng.state.players
    for owner in ['p1','p1','p2','p2']:emblem(eng,owner)
    p.life=q.life=0
    eng.rules.check_state_based_actions()
    assert eng.state.pending_choice['player_id']=='p1'
    answer(eng,1)
    assert eng.state.pending_choice['player_id']=='p2'
    assert not eng.state.game_over and not p.has_lost and not q.has_lost
    answer(eng,0)
    assert p.life==q.life==20 and len(p.emblems)==len(q.emblems)==1
    assert not eng.state.game_over and eng.state.player_loss_batch is None


def test_commander_damage_is_independent_and_can_lose_again_after_rescue():
    eng=engine();p=eng.state.players[0];emblem(eng)
    p.commander_damage['cmd']={'amount':21}
    eng.rules.check_state_based_actions()
    assert p.life==20 and p.has_lost and p.loss_reason=='commander_damage' and not p.emblems


def test_cant_lose_consumes_no_emblem_and_failed_draw_is_not_permanent():
    eng=engine();p=eng.state.players[0];em=emblem(eng)
    shield=WinConditionEffect()
    p.player_effects.append(shield)
    eng.rules.draw(p,1);assert p.loss_reason is None
    eng.rules.check_state_based_actions()
    assert not p.has_lost and not p.attempted_draw_from_empty and em in p.emblems
    p.player_effects.remove(shield);eng.rules.check_state_based_actions()
    assert em in p.emblems and not p.has_lost
    eng.rules.draw(p,1);eng.rules.check_state_based_actions()
    assert not p.emblems and not p.has_lost

@pytest.mark.parametrize('terminal',['conceded','opponent_won'])
def test_terminal_concession_and_explicit_opponent_win_bypass_emblem_and_cantlose(terminal):
    eng=engine();p,q=eng.state.players;em=emblem(eng)
    p.player_effects.append(WinConditionEffect())
    if terminal=='conceded':eng.rules.concede(p)
    else:eng.rules.player_wins(q)
    assert p.has_lost and p.loss_reason==terminal and em in p.emblems
    assert eng.state.game_over and eng.state.winner_id==q.id


def gain_replacements(p):
    p.player_effects.extend([
        ReplacementEffect(EventType.LIFE_GAIN,lambda e,c:e.copy_with(amount=e.get('amount')*2),condition=lambda e,c,pid=p.id:e.get('player_id')==pid,description='Double'),
        ReplacementEffect(EventType.LIFE_GAIN,lambda e,c:e.copy_with(amount=e.get('amount')+1),condition=lambda e,c,pid=p.id:e.get('player_id')==pid,description='Plus one'),
    ])


def test_nested_life_gain_order_pauses_payload_and_then_next_players_loss():
    eng=engine();p,q=eng.state.players;em=emblem(eng);gain_replacements(p)
    grave=obj(eng,'Grave',zone=Zone.GRAVEYARD);p.life=0;p.poison=10;q.life=0
    eng.rules.check_state_based_actions()
    assert eng.state.pending_choice['kind']=='replacement_order' and eng.state.pending_choice['player_id']=='p1'
    assert grave in p.graveyard and p.poison==10 and em in p.emblems and not q.has_lost
    answer(eng,1)
    assert p.life==42 and grave in p.library and p.poison==0 and em not in p.emblems
    assert q.has_lost and eng.state.game_over and eng.state.winner_id==p.id


def test_life_gain_prevention_does_not_turn_becomes_twenty_into_raw_assignment():
    eng=engine();p=eng.state.players[0];emblem(eng);p.life=0
    eng.rules.prevent_life_gain_this_turn([p])
    eng.rules.check_state_based_actions()
    assert p.life==0 and not p.emblems and p.has_lost


def test_effect_sequence_resumes_only_after_recovery_payload():
    eng=engine();p=eng.state.players[0];source=obj(eng);emblem(eng);gain_replacements(p);p.life=1
    _apply_effects_partitioned([LoseGameEffect(source=source),GainLifeEffect(3,target_kind=None,source=source)],
                               GameContext(eng.state,eng.rules),None,None,source=source)
    assert p.life==1 and eng.state.pending_choice
    answer(eng,0)
    # The following gain itself has two replacements and must still be chosen.
    assert eng.state.pending_choice and p.life==40 and not p.emblems
    answer(eng,0)
    assert p.life==47 and not p.has_lost and not eng.state.deferred_effects


def test_pending_loss_choice_clone_restores_live_emblem_and_current_engine_continuation():
    eng=engine();p=eng.state.players[0];a=emblem(eng);b=emblem(eng);p.life=0
    eng.rules.check_state_based_actions()
    clone=eng.state.clone();restored=GameEngine(clone)
    cloned_emblems=clone.players[0].emblems
    assert clone.replacement_continuation['applicable'][1] is cloned_emblems[1].replacement_effects[0]
    answer(restored,1)
    assert clone.players[0].life==20 and clone.players[0].emblems==[cloned_emblems[0]]
    assert p.life==0 and p.emblems==[a,b] and eng.state.pending_choice


def test_pending_nested_life_choice_clone_restores_payload_and_batch():
    eng=engine();p=eng.state.players[0];emblem(eng);gain_replacements(p);p.life=0
    eng.rules.check_state_based_actions();clone=eng.state.clone();restored=GameEngine(clone)
    answer(restored,0)
    assert clone.players[0].life==41 and not clone.players[0].emblems
    assert clone.player_loss_batch is None and not clone.deferred_effects and p.life==0


def test_real_full_puresteel_oracle_etb_combat_emblem_and_source_departure():
    eng=engine();p,q=eng.state.players
    colored=obj(eng,'Colored',type_line='Artifact',color_identity={'U'})
    colorless=obj(eng,'Colorless',type_line='Artifact')
    angel=obj(eng,'Puresteel Angel',type_line='Artifact Creature — Angel',is_creature=True,
              power=4,toughness=4,oracle_text=ORACLE)
    assert parse_oracle(angel.card).modeled
    eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD,instance_id=angel.instance_id,controller_id='p1'))
    eng.resolve_until_stable()
    assert colored in p.exile and colorless in eng.state.battlefield and angel in eng.state.battlefield
    eng.rules.deal_damage(q,4,source=angel,combat=True);eng.resolve_until_stable()
    assert len(p.emblems)==1 and p.emblems[0].replacement_effects
    eng.rules.exile(angel);p.life=0;eng.resolve_until_stable()
    assert p.life==20 and not p.has_lost and not p.emblems


def test_almost_matching_recovery_payload_stays_unmodeled():
    assert match_clause('you get an emblem with "'+BODY.lower().replace('20','30')+'"') is None
    assert match_clause('you get an emblem with "'+BODY.lower().replace('poison counters','energy counters')+'"') is None


def test_effect_driven_multiplayer_losses_choose_apnap_even_when_input_order_differs():
    eng=engine(3);eng.state.active_player_index=2
    for owner in ['p2','p2','p3','p3']:emblem(eng,owner)
    eng.rules._lose_players([('p2','effect'),('p3','effect'),('p2','effect')])
    assert eng.state.pending_choice['player_id']=='p3'
    answer(eng,1)
    assert eng.state.pending_choice['player_id']=='p2'
    answer(eng,0)
    assert all(not p.has_lost for p in eng.state.players)
    assert len(eng.state.players[1].emblems)==len(eng.state.players[2].emblems)==1


def test_angel_of_destiny_effect_uses_one_simultaneous_multiplayer_batch():
    eng=engine(3);source=obj(eng)
    for owner in ['p2','p2','p3','p3']:emblem(eng,owner)
    for defender in ['p2','p3']:
        eng.state.fire_event(GameEvent(EventType.ATTACKS,instance_id=source.instance_id,
                                      defending_player_id=defender,defender_kind='player',declared=True))
    LoseGameEffect(players='attacked_by_source_this_turn',source=source).apply(GameContext(eng.state,eng.rules))
    assert eng.state.pending_choice['player_id']=='p2'
    answer(eng,0);assert eng.state.pending_choice['player_id']=='p3'
    answer(eng,0);assert all(not p.has_lost for p in eng.state.players)


def test_pass_priority_does_not_grant_new_window_during_nested_recovery(monkeypatch):
    from mtg_analyzer.models.game.game_state import StackItem
    eng=engine();source=obj(eng);emblem(eng);gain_replacements(eng.state.players[0]);eng.state.players[0].life=1
    eng.state.stack.append(StackItem('ability',effects=[LoseGameEffect(source=source)],source=source,controller_id='p1'))
    windows=[];monkeypatch.setattr(eng,'give_priority',lambda p:windows.append(p.id))
    assert eng.pass_priority()
    assert eng.state.pending_choice and not windows


def test_session_rewind_pending_emblem_choice_can_be_answered_again():
    from mtg_analyzer.services.game_session import GameSession
    eng=engine();p=eng.state.players[0];first=emblem(eng);second=emblem(eng);p.life=0
    eng.rules.check_state_based_actions();session=GameSession(eng)
    session.apply_action({'type':'choose','option_id':'1'},actor_id='p1')
    assert len(session.engine.state.players[0].emblems)==1
    session.rewind()
    restored=session.engine.state.players[0]
    assert restored.life==0 and [e.instance_id for e in restored.emblems]==[first.instance_id,second.instance_id]
    assert session.engine.state.pending_choice['kind']=='replacement_order'
    session.apply_action({'type':'choose','option_id':'0'},actor_id='p1')
    assert restored.life==20 and [e.instance_id for e in restored.emblems]==[second.instance_id]
    assert not restored.has_lost and session.engine.state.player_loss_batch is None


def test_session_rewind_nested_life_choice_restores_deferred_payload():
    from mtg_analyzer.services.game_session import GameSession
    eng=engine();p=eng.state.players[0];em=emblem(eng);gain_replacements(p);p.life=0;p.poison=11
    grave=obj(eng,'Grave',zone=Zone.GRAVEYARD)
    eng.rules.check_state_based_actions();session=GameSession(eng)
    session.apply_action({'type':'choose','option_id':'0'},actor_id='p1');session.rewind()
    restored=session.engine.state.players[0]
    assert restored.life==0 and restored.poison==11 and restored.emblems[0].instance_id==em.instance_id
    assert restored.graveyard[0].instance_id==grave.instance_id
    session.apply_action({'type':'choose','option_id':'1'},actor_id='p1')
    assert restored.life==42 and restored.poison==0 and not restored.emblems and not restored.graveyard
    assert session.engine.state.player_loss_batch is None and not session.engine.state.deferred_effects


def test_recovery_shuffle_uses_real_graveyard_exits_and_invalidates_old_visit():
    from mtg_analyzer.game.effects.returns_graveyards import ReturnRememberedGraveyardCardsEffect
    eng=engine();p=eng.state.players[0];emblem(eng)
    grave=obj(eng,'Remembered',zone=Zone.GRAVEYARD,type_line='Creature',is_creature=True,power=2,toughness=2)
    iid=grave.instance_id;old_incarnation=grave.zone_incarnation
    stale=ReturnRememberedGraveyardCardsEffect([iid],graveyard_incarnations={str(iid):old_incarnation})
    eng.state.temp_graveyard_cast_permissions[iid]={'test_permission':True}
    p.life=0;eng.rules.check_state_based_actions()
    assert grave.instance_id==iid and grave.zone_incarnation!=old_incarnation and grave in p.library
    assert iid not in eng.state.temp_graveyard_cast_permissions
    exits=[e for e in eng.state.event_log if e.type==EventType.CARD_LEFT_GRAVEYARD]
    assert any(e.get('instance_id')==iid for e in exits)
    assert p.id in eng.state.cards_left_graveyard_this_turn
    # Reentering that graveyard does not revive an older captured reference.
    p.library.remove(grave);p.add_to_zone(grave,Zone.GRAVEYARD)
    stale.apply(GameContext(eng.state,eng.rules))
    assert grave in p.graveyard and grave not in eng.state.battlefield


def test_recovery_shuffle_serializes_commander_choices_before_payload_finishes():
    eng=engine();p=eng.state.players[0];em=emblem(eng)
    first=obj(eng,'CommanderA',zone=Zone.GRAVEYARD);first.is_commander=True
    second=obj(eng,'CommanderB',zone=Zone.GRAVEYARD);second.is_commander=True
    p.life=0;p.poison=10
    eng.rules.check_state_based_actions()
    assert eng.state.pending_choice['instance_id']==first.instance_id
    assert second in p.graveyard and p.poison==10 and em in p.emblems
    eng.resolve_pending_choice('decline')
    assert eng.state.pending_choice['instance_id']==second.instance_id
    assert p.poison==10 and em in p.emblems
    eng.resolve_pending_choice('command')
    assert first in p.library and second.zone==Zone.COMMAND
    assert not p.emblems and p.poison==0 and not p.has_lost and eng.state.player_loss_batch is None
    assert sum(e.type==EventType.SHUFFLE for e in eng.state.event_log)==1


@pytest.mark.parametrize('commanders',[False,True])
def test_graveyard_shuffle_is_one_leave_event_and_one_real_one_or_more_trigger(commanders):
    from mtg_analyzer.game.effects.exile_control import ShuffleGraveyardIntoLibraryEffect
    eng=engine(3);p=eng.state.players[0]
    watcher=obj(eng,'Grave watcher',oracle_text='Whenever one or more cards leave your graveyard, create a tapped 2/2 black Zombie creature token.')
    assert len(watcher.triggered_abilities)==1
    first=obj(eng,'A',zone=Zone.GRAVEYARD);second=obj(eng,'B',zone=Zone.GRAVEYARD)
    first.is_commander=second.is_commander=commanders
    ShuffleGraveyardIntoLibraryEffect(source=watcher).apply(GameContext(eng.state,eng.rules))
    if commanders:
        assert not any(e.type==EventType.CARDS_LEFT_GRAVEYARD for e in eng.state.event_log)
        eng.resolve_pending_choice('decline')
        assert eng.state.pending_choice['instance_id']==second.instance_id
        assert not any(e.type==EventType.CARDS_LEFT_GRAVEYARD for e in eng.state.event_log)
        eng.resolve_pending_choice('decline')
    eng.resolve_until_stable()
    groups=[e for e in eng.state.event_log if e.type==EventType.CARDS_LEFT_GRAVEYARD]
    assert len(groups)==1 and {r['instance_id'] for r in groups[0].get('cards')}=={first.instance_id,second.instance_id}
    zombies=[o for o in eng.state.battlefield if o.is_token and o.name=='Zombie']
    assert len(zombies)==1 and zombies[0].tapped and not eng.state._batch_hold


def test_paused_graveyard_shuffle_batch_survives_clone_and_does_not_release_outer_hold():
    from mtg_analyzer.game.effects.exile_control import ShuffleGraveyardIntoLibraryEffect
    eng=engine(3);p=eng.state.players[0];source=obj(eng)
    first=obj(eng,'A',zone=Zone.GRAVEYARD);second=obj(eng,'B',zone=Zone.GRAVEYARD)
    first.is_commander=second.is_commander=True
    eng.state.hold_batches()
    ShuffleGraveyardIntoLibraryEffect(source=source).apply(GameContext(eng.state,eng.rules))
    restored=GameEngine(eng.state.clone())
    restored.resolve_pending_choice('decline');restored.resolve_pending_choice('decline')
    assert restored.state._batch_hold
    assert not any(e.type==EventType.CARDS_LEFT_GRAVEYARD for e in restored.state.event_log)
    restored.state.release_batches()
    groups=[e for e in restored.state.event_log if e.type==EventType.CARDS_LEFT_GRAVEYARD]
    assert len(groups)==1 and len(groups[0].get('cards'))==2


@pytest.mark.parametrize('stage',['loss','life_gain','commander'])
def test_session_concession_cancels_only_own_recovery_and_continues_other_players(stage):
    from mtg_analyzer.services.game_session import GameSession
    eng=engine(3);p,q,r=eng.state.players
    unused=[emblem(eng)]
    if stage=='loss':unused.append(emblem(eng))
    if stage=='life_gain':gain_replacements(p)
    if stage=='commander':
        card=obj(eng,'Commander',zone=Zone.GRAVEYARD);card.is_commander=True
    emblem(eng,'p2');emblem(eng,'p2')
    p.life=q.life=0;p.poison=11
    eng.rules.check_state_based_actions()
    assert eng.state.pending_choice['player_id']=='p1'
    session=GameSession(eng);session.concede('p1')
    assert p.has_lost and p.loss_reason=='conceded' and p.emblems==unused and p.poison==11
    assert eng.state.pending_choice['player_id']=='p2' and not eng.state.game_over
    session.apply_action({'type':'choose','option_id':'1'},actor_id='p2')
    assert q.life==20 and not q.has_lost and len(q.emblems)==1
    assert not eng.state.pending_choice and eng.state.player_loss_batch is None and not eng.state.deferred_effects
    assert not eng.state._batch_hold and not eng.state.game_over and not r.has_lost


def test_session_concession_preserves_another_players_outer_resolution_tail():
    from mtg_analyzer.services.game_session import GameSession
    eng=engine(3);p,q,r=eng.state.players;source=obj(eng,owner='p3');initial_life=r.life
    emblem(eng,'p2');gain_replacements(q);q.life=1
    eng.state.fire_event(GameEvent(EventType.ATTACKS,instance_id=source.instance_id,
                                  defending_player_id='p2',defender_kind='player',declared=True))
    _apply_effects_partitioned([
        LoseGameEffect(players='attacked_by_source_this_turn',source=source),
        GainLifeEffect(3,target_kind=None,source=source),
    ],GameContext(eng.state,eng.rules),None,None,source=source)
    assert eng.state.pending_choice['player_id']=='p2' and r.life==initial_life
    session=GameSession(eng);session.concede('p2')
    assert q.has_lost and r.life==initial_life+3 and len(q.emblems)==1
    assert not eng.state.pending_choice and not eng.state.deferred_effects and eng.state.player_loss_batch is None


def test_conceding_future_loser_does_not_cancel_current_players_choice():
    from mtg_analyzer.services.game_session import GameSession
    eng=engine(3);p,q,r=eng.state.players
    first=emblem(eng);second=emblem(eng);emblem(eng,'p2');p.life=q.life=0
    eng.rules.check_state_based_actions();session=GameSession(eng);session.concede('p2')
    assert eng.state.pending_choice['player_id']=='p1' and p.emblems==[first,second]
    session.apply_action({'type':'choose','option_id':'0'},actor_id='p1')
    assert not p.has_lost and q.has_lost and not eng.state.pending_choice and eng.state.player_loss_batch is None


def test_terminal_concession_clears_pending_recovery_without_consuming_emblems():
    from mtg_analyzer.services.game_session import GameSession
    eng=engine();p,q=eng.state.players;first=emblem(eng);second=emblem(eng);p.life=0
    eng.rules.check_state_based_actions();session=GameSession(eng);session.concede('p1')
    assert eng.state.game_over and eng.state.winner_id==q.id and p.emblems==[first,second]
    assert eng.state.pending_choice is None and eng.state.player_loss_batch is None
    assert eng.state.pending_leave_ids==[] and not eng.state.deferred_effects


@pytest.mark.parametrize('outer_hold',[False,True])
def test_shared_shuffle_concession_cancels_own_commander_choice_and_preserves_outer_tail(outer_hold):
    from mtg_analyzer.game.effects.exile_control import ShuffleGraveyardIntoLibraryEffect
    from mtg_analyzer.services.game_session import GameSession
    eng=engine(3);p,q,r=eng.state.players;source=obj(eng,owner='p1');other=obj(eng,owner='p3')
    initial_life=r.life
    first=obj(eng,'A',zone=Zone.GRAVEYARD);first.is_commander=True
    second=obj(eng,'B',zone=Zone.GRAVEYARD)
    if outer_hold:eng.state.hold_batches()
    _apply_effects_partitioned([
        ShuffleGraveyardIntoLibraryEffect(source=source),
        GainLifeEffect(3,target_kind=None,source=other),
    ],GameContext(eng.state,eng.rules),None,None,source=other)
    assert eng.state.pending_choice['instance_id']==first.instance_id and second in p.graveyard
    session=GameSession(eng);session.concede('p1')
    assert p.has_lost and r.life==initial_life+3 and second in p.graveyard
    assert eng.state.pending_choice is None and not eng.state.deferred_effects
    assert eng.state._batch_hold==outer_hold
    if outer_hold:eng.state.release_batches()
    assert sum(e.type==EventType.SHUFFLE for e in eng.state.event_log)==0
    exits=[e for e in eng.state.event_log if e.type==EventType.CARDS_LEFT_GRAVEYARD]
    assert len(exits)==1 and len(exits[0].get('cards'))==1


def test_session_rewind_concession_restores_pending_commander_recovery_and_batch_hold():
    from mtg_analyzer.services.game_session import GameSession
    eng=engine(3);p=eng.state.players[0];em=emblem(eng)
    first=obj(eng,'A',zone=Zone.GRAVEYARD);second=obj(eng,'B',zone=Zone.GRAVEYARD)
    first.is_commander=second.is_commander=True
    p.life=0;p.poison=11;eng.rules.check_state_based_actions()
    session=GameSession(eng);session.concede('p1');session.rewind()
    restored=session.engine.state.players[0]
    assert not restored.has_lost and restored.emblems[0].instance_id==em.instance_id
    assert session.engine.state.pending_choice['instance_id']==first.instance_id and session.engine.state._batch_hold
    session.apply_action({'type':'choose','option_id':'decline'},actor_id='p1')
    assert session.engine.state.pending_choice['instance_id']==second.instance_id
    session.apply_action({'type':'choose','option_id':'decline'},actor_id='p1')
    assert restored.life==20 and restored.poison==0 and not restored.emblems
    assert not session.engine.state._batch_hold and session.engine.state.player_loss_batch is None
    groups=[e for e in session.engine.state.event_log if e.type==EventType.CARDS_LEFT_GRAVEYARD]
    assert len(groups)==1 and len(groups[0].get('cards'))==2


@pytest.mark.parametrize('stage',['loss','life_gain','commander'])
def test_explicit_multiplayer_win_cancels_all_rescues_without_consuming_unused_emblems(stage):
    eng=engine(3);p,q,r=eng.state.players
    unused=[emblem(eng)]
    if stage=='loss':unused.append(emblem(eng))
    if stage=='life_gain':gain_replacements(p)
    if stage=='commander':
        card=obj(eng,'Commander',zone=Zone.GRAVEYARD);card.is_commander=True
    other=emblem(eng,'p3');p.life=r.life=0
    eng.rules.check_state_based_actions();assert eng.state.pending_choice['player_id']=='p1'
    eng.rules.player_wins(q)
    assert eng.state.game_over and eng.state.winner_id==q.id
    assert p.emblems==unused and r.emblems==[other] and p.has_lost and r.has_lost
    assert eng.state.pending_choice is None and eng.state.player_loss_batch is None
    assert not eng.state.deferred_effects and not eng.state._batch_hold

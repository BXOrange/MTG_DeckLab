"""Opponent-step statics modify turn-based actions, with no stack/priority gap."""
import pytest
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.binding.core import bind_from_catalogue,build_effects
from mtg_analyzer.game.effects.core import GameContext,ReplacementEffect
from mtg_analyzer.game.phases import GamePhase,GameStep
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject,Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.services.game_session import GameSession

BODY='you get an emblem with "untap all permanents you control during each opponent\'s untap step" and "you draw a card during each opponent\'s draw step."'

def engine(n=2):
    land=Card(id='Forest',name='Forest',type_line='Basic Land — Forest',is_land=True)
    eng=GameEngine.new_game([(f'p{i+1}',f'P{i+1}',[land]*12) for i in range(n)],starting_hand=0,starting_life=20)
    eng.state.internal_turn.number=2;eng.state.current_step='main1';eng.state.skip_first_draw=False
    return eng

def put(eng,name='Source',owner='p1',zone=Zone.BATTLEFIELD,**kw):
    c=Card(id=name,name=name,type_line=kw.pop('type_line','Enchantment'),**kw)
    o=GameObject(c,owner_id=owner,zone=zone);bind_from_catalogue(o)
    if zone==Zone.BATTLEFIELD:eng.state.add_to_battlefield(o)
    else:eng.state.player_by_id(owner).add_to_zone(o,zone)
    return o

def real_card(eng,name,owner='p1',zone=Zone.BATTLEFIELD):
    from mtg_analyzer.services.card_database import CardDatabase,DEFAULT_DB_PATH
    card=CardDatabase(DEFAULT_DB_PATH).get_card(name);assert card is not None
    o=GameObject(card,owner_id=owner,zone=zone);bind_from_catalogue(o)
    if zone==Zone.BATTLEFIELD:eng.state.add_to_battlefield(o)
    else:eng.state.player_by_id(owner).add_to_zone(o,zone)
    return o

def emblem(eng,owner='p1'):
    src=put(eng,owner=owner);specs=match_clause(BODY);assert specs
    for effect in build_effects(specs,src):effect.apply(GameContext(eng.state,eng.rules))
    eng.rules.exile(src)
    return eng.state.player_by_id(owner).emblems[-1]

def step(eng,name='draw',active='p2'):
    eng.state.active_player_index=next(i for i,p in enumerate(eng.state.players) if p.id==active)
    eng._run_step(GamePhase('beginning',[]),GameStep(name,gives_priority=name!='untap'))

def draws(eng):return [e.get('player_id') for e in eng.state.event_log if e.type==EventType.DRAW and e.get('instance_ids')]

def dredge(eng,owner):
    return real_card(eng,'Stinkweed Imp',owner,Zone.GRAVEYARD)


def draw_replacements(eng,player_id):
    p=eng.state.player_by_id(player_id)
    p.player_effects.extend([ReplacementEffect(EventType.DRAW,lambda e,c:e.copy_with(count=1),
        condition=lambda e,c,pid=player_id:e.get('player_id')==pid,description=str(i)) for i in range(2)])


def test_real_loyalty_emblem_works_after_walker_leaves_as_two_statics():
    eng=engine();p=eng.state.players[0]
    walker=put(eng,'Teferi, Who Slows the Sunset',type_line='Legendary Planeswalker — Teferi',loyalty=7)
    walker.counters['loyalty']=7
    eng.activate_ability(p,walker,2);eng.resolve_until_stable()
    assert walker not in eng.state.battlefield and len(p.emblems)==1
    assert not p.emblems[0].triggered_abilities and len(p.emblems[0].static_effects)==2
    mine=put(eng,'Mine');theirs=put(eng,'Theirs',owner='p2');mine.tapped=theirs.tapped=True
    step(eng,'untap');assert not mine.tapped and not theirs.tapped and not eng.state.stack
    step(eng);assert draws(eng)==['p2','p1'] and not eng.state.stack


def test_generic_emblems_each_draw_once_active_first_then_holders_apnap():
    eng=engine(3);emblem(eng,'p1');emblem(eng,'p1');emblem(eng,'p3');emblem(eng,'p2')
    step(eng,active='p2')
    assert draws(eng)==['p2','p3','p1','p1']
    assert not eng.state.turn_based_draws and not eng.state.stack


def test_active_dredge_pauses_everything_until_its_draw_then_holder_dredge():
    eng=engine();emblem(eng);active=dredge(eng,'p2');holder=dredge(eng,'p1')
    step(eng)
    assert eng.state.pending_choice['player_id']=='p2' and not draws(eng)
    assert eng.state.priority_player_index is None and not eng.state.stack
    eng.resolve_pending_choice('draw')
    assert draws(eng)==['p2'] and eng.state.pending_choice['player_id']=='p1'
    assert eng.state.priority_player_index is None
    eng.resolve_pending_choice(str(holder.instance_id))
    assert holder in eng.state.players[0].hand and draws(eng)==['p2']
    assert eng.state.turn_based_draws is None and eng.state.pending_turn_step is None


def test_draw_replacement_choice_clone_and_session_rewind_resume_current_state():
    eng=engine();emblem(eng);draw_replacements(eng,'p2');step(eng)
    clone=eng.state.clone();restored=GameEngine(clone);restored.resolve_pending_choice('1')
    assert draws(restored)==['p2','p1'] and not draws(eng)
    session=GameSession(eng);session.apply_action({'type':'choose','option_id':'0'},actor_id='p2')
    assert draws(eng)==['p2','p1'];session.rewind()
    assert not draws(session.engine) and session.engine.state.pending_choice['player_id']=='p2'
    session.apply_action({'type':'choose','option_id':'1'},actor_id='p2')
    assert draws(session.engine)==['p2','p1']


def test_miracle_reveal_waits_for_holder_draw_before_trigger_announcement():
    eng=engine();emblem(eng);eng.interactive_priority=True
    miracle=real_card(eng,'Terminus','p2',Zone.LIBRARY)
    step(eng)
    assert eng.state.pending_choice['kind']=='miracle_reveal' and draws(eng)==['p2']
    assert not eng.state.stack and eng.state.priority_player_index is None
    eng.resolve_pending_choice('reveal')
    assert draws(eng)==['p2','p1'] and len(eng.state.stack)==1
    assert eng.state.turn_based_draws is None and eng.state.pending_choice is None


def test_dredge_mill_replacement_choice_pauses_return_and_survives_clone():
    eng=engine();emblem(eng);card=dredge(eng,'p2');p=eng.state.players[1]
    p.player_effects.extend([ReplacementEffect(EventType.WOULD_MILL,lambda e,c:e,
                                             description=str(i)) for i in range(2)])
    step(eng);eng.resolve_pending_choice(str(card.instance_id))
    assert eng.state.pending_choice['kind']=='replacement_order' and card in p.graveyard and not draws(eng)
    restored=GameEngine(eng.state.clone());restored.resolve_pending_choice('0')
    assert restored.state.find_object(card.instance_id) in restored.state.players[1].hand
    assert draws(restored)==['p1'] and card in p.graveyard


@pytest.mark.parametrize('skip_first',[False,True])
def test_skipped_whole_draw_step_has_no_holder_draw_or_begin_step_trigger(skip_first):
    eng=engine();emblem(eng)
    if skip_first:
        eng.state.skip_first_draw=True;eng.state.internal_turn.number=1
    else:
        from mtg_analyzer.game.effects.core import StaticEffect
        # A real standing skip (Necropotence) uses the same whole-step gate.
        real_card(eng,'Necropotence','p2')
    step(eng)
    assert not draws(eng) and not eng.state.turn_based_draws
    assert not any(e.type==EventType.STEP_BEGIN and e.get('step')=='draw' for e in eng.state.event_log)


def test_replacing_individual_active_draw_does_not_skip_holder_draw():
    eng=engine();emblem(eng);p=eng.state.players[1]
    p.player_effects.append(ReplacementEffect(EventType.DRAW,lambda e,c:None,
        condition=lambda e,c:e.get('player_id')=='p2'))
    step(eng);assert draws(eng)==['p1']


def test_empty_active_library_sba_waits_until_holder_draw_completed():
    eng=engine(3);emblem(eng);eng.state.players[1].library.clear()
    seen=[];eng.state.subscribe(lambda event:seen.append((event.type,event.get('player_id'))))
    step(eng)
    draw_index=next(i for i,e in enumerate(seen) if e==(EventType.DRAW,'p1'))
    loss_index=next(i for i,e in enumerate(seen) if e==(EventType.PLAYER_LOST,'p2'))
    assert draw_index<loss_index


def test_concession_during_active_dredge_continues_other_holders_without_deadlock():
    eng=engine(3);emblem(eng);dredge(eng,'p2');step(eng)
    session=GameSession(eng);session.concede('p2')
    assert draws(eng)==['p1'] and eng.state.players[1].has_lost
    assert eng.state.pending_choice is None and eng.state.turn_based_draws is None
    assert eng.state.priority_player.id!='p2'


def test_untap_static_respects_stun_and_no_untap_but_foreign_draw_holder_ignores_active_orb_cap():
    eng=engine();emblem(eng)
    land1=put(eng,'L1',type_line='Land',is_land=True);land2=put(eng,'L2',type_line='Land',is_land=True)
    stunned=put(eng,'Stunned');stunned.counters['stun']=1
    locked=put(eng,'Locked',oracle_text="This enchantment doesn't untap during your untap step.")
    orb=put(eng,'Winter Orb',type_line='Artifact')
    for o in [land1,land2,stunned,locked]:o.tapped=True
    step(eng,'untap')
    assert not land1.tapped and not land2.tapped and stunned.tapped and stunned.counters.get('stun',0)==0
    # The own-untap restriction is not a prohibition on foreign-step untaps.
    assert not locked.tapped


def test_beginning_and_delayed_draw_step_triggers_wait_for_all_draws_and_survive_clone():
    from mtg_analyzer.models.game.game_state import DelayedTrigger
    from mtg_analyzer.game.effects.life_sacrifice import GainLifeEffect
    eng=engine();emblem(eng);draw_replacements(eng,'p2');eng.interactive_priority=True
    watch=put(eng,'Watch',oracle_text='At the beginning of each draw step, you gain 1 life.')
    assert len(watch.triggered_abilities)==1
    eng.state.delayed_triggers.append(DelayedTrigger(controller_id='p1',step='draw',scope='any',effects=[GainLifeEffect(2,target_kind=None,source=watch)]))
    step(eng)
    assert eng.state.pending_choice and not eng.state.stack and len(eng.state.turn_draw_delayed_triggers)==1
    assert len(eng.rules.pending_triggers)==1
    restored=GameEngine(eng.state.clone());restored.interactive_priority=True
    restored.resolve_pending_choice('0')
    assert draws(restored)==['p2','p1'] and len(restored.state.stack)==2
    assert not restored.state.turn_draw_delayed_triggers and restored.state.turn_draw_pending_triggers is None
    assert restored.state.players[0].life==20


def test_draw_limit_applies_per_emblem_and_cannot_be_replaced_by_dredge():
    eng=engine();emblem(eng);emblem(eng);real_card(eng,'Spirit of the Labyrinth')
    card=dredge(eng,'p1')
    step(eng)
    assert eng.state.pending_choice['player_id']=='p1'
    eng.resolve_pending_choice('draw')
    assert draws(eng)==['p2','p1'] and eng.state.pending_choice is None and card in eng.state.players[0].graveyard


def test_holder_draw_is_not_the_active_players_first_draw_exemption_and_steps_repeat():
    eng=engine();emblem(eng)
    step(eng);step(eng)
    events=[e for e in eng.state.event_log if e.type==EventType.DRAW and e.get('instance_ids')]
    assert [(e.get('player_id'),e.get('first_in_draw_step')) for e in events]==[
        ('p2',True),('p1',False),('p2',True),('p1',False)]


def test_controlled_turn_routes_active_draw_choice_to_turn_controller_without_reordering():
    from mtg_analyzer.models.game.game_state import TurnControl
    eng=engine();emblem(eng);dredge(eng,'p2')
    control=TurnControl('p2','p1',0);control.phase='active';eng.state.turn_controls.append(control)
    step(eng);session=GameSession(eng)
    assert eng.state.pending_choice['player_id']=='p2'
    session.apply_action({'type':'choose','option_id':'draw'},actor_id='p1')
    assert draws(eng)==['p2','p1'] and not eng.state.pending_choice


def test_holder_concession_during_its_choice_skips_remaining_copies_and_finishes_step():
    eng=engine(3);emblem(eng);emblem(eng);dredge(eng,'p1');step(eng)
    assert draws(eng)==['p2'] and eng.state.pending_choice['player_id']=='p1'
    session=GameSession(eng);session.concede('p1')
    assert draws(eng)==['p2'] and eng.state.turn_based_draws is None and eng.state.pending_turn_step is None
    assert eng.state.pending_choice is None and eng.state.priority_player.id=='p2'


def test_miracle_holder_reveal_does_not_lose_remaining_emblem_draw_on_undo():
    eng=engine();emblem(eng);emblem(eng);real_card(eng,'Terminus','p1',Zone.LIBRARY)
    step(eng);assert eng.state.pending_choice['kind']=='miracle_reveal'
    session=GameSession(eng);session.apply_action({'type':'choose','option_id':'decline'},actor_id='p1')
    assert draws(eng)==['p2','p1','p1'];session.rewind()
    assert draws(session.engine)==['p2','p1']
    session.apply_action({'type':'choose','option_id':'decline'},actor_id='p1')
    assert draws(session.engine)==['p2','p1','p1'] and not session.engine.state.pending_turn_step


def test_seedborn_uses_shared_simultaneous_static_and_preserves_own_step_freeze_flags():
    eng=engine();muse=real_card(eng,'Seedborn Muse')
    assert not muse.triggered_abilities
    frozen=put(eng,'Frozen');frozen.tapped=True;frozen.skip_next_untap=True
    stun=put(eng,'Stun');stun.tapped=True;stun.counters['stun']=1
    phased=put(eng,'Phased');phased.tapped=True;phased.phased_out=True
    locked=real_card(eng,'Basalt Monolith');locked.tapped=True
    step(eng,'untap')
    assert not frozen.tapped and frozen.skip_next_untap
    assert stun.tapped and not stun.counters.get('stun') and phased.tapped and not locked.tapped
    frozen.tapped=True;locked.tapped=True
    step(eng,'untap',active='p1')
    assert frozen.tapped and not frozen.skip_next_untap and locked.tapped


def test_stasis_skips_foreign_untap_as_well():
    eng=engine();emblem(eng);real_card(eng,'Stasis')
    mine=put(eng,'Mine');mine.tapped=True
    step(eng,'untap');assert mine.tapped


def test_draw_sba_replacement_waits_until_holder_draw_and_resumes_step_window_once():
    from tests.test_mec121_loss_replacement import emblem as rescue
    eng=engine(3);emblem(eng);rescue(eng,'p2');rescue(eng,'p2');eng.state.players[1].library.clear()
    step(eng)
    assert draws(eng)==['p1'] and eng.state.pending_choice['player_id']=='p2'
    assert eng.state.priority_player_index is None and eng.state.pending_turn_step is not None
    restored=GameEngine(eng.state.clone());restored.resolve_pending_choice('0')
    assert restored.state.pending_turn_step is None and not restored.state.players[1].has_lost
    assert sum(e.type==EventType.STEP_END and e.get('step')=='draw' for e in restored.state.event_log)==1

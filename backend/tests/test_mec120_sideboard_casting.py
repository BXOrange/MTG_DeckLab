"""Outside-game casting uses the real emblem and ordinary engine pipeline."""
import pytest
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.services.game_session import GameActionError, GameSession, build_goldfish_engine

BODY='you get an emblem with "you can cast nonland cards from your sideboard."'
def card(name='Outside',kind='Creature',cost='{1}'):
    return Card(id=name,name=name,type_line=kind,oracle_text='',mana_cost_string=cost,
                is_creature=kind=='Creature',is_instant=kind=='Instant',is_sorcery=kind=='Sorcery',
                is_land=kind=='Land',power=2 if kind=='Creature' else None,toughness=2 if kind=='Creature' else None)
def engine(cards=None):
    eng=GameEngine.new_game([('p1','P1',[]),('p2','P2',[])],starting_hand=0,
                            player_sideboards={'p1':cards or [card()]})
    eng.state.current_step='main1'
    return eng

def permission(eng,owner='p1'):
    src=GameObject(card('Source','Enchantment','{0}'),owner_id=owner,zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(src)
    specs=match_clause(BODY);assert specs
    for effect in build_effects(specs,source=src):effect.apply(GameContext(eng.state,eng.rules))
    eng.rules.destroy(src)


def test_real_emblem_paid_cast_keeps_identity_and_leaves_outside_game():
    eng=engine();p=eng.state.players[0];obj=p.sideboard[0]
    assert obj.zone is None and obj not in sum(p.zones.values(),[])
    assert eng.state.find_object(obj.instance_id) is obj
    assert not eng.can_cast(p,obj)
    permission(eng)
    assert not eng.can_cast(p,obj)
    p.mana_pool.add('C',1)
    assert eng.can_cast(p,obj)
    assert any(a.get('instance_id')==obj.instance_id for a in eng.legal_actions(p))
    eng.cast_spell(p,obj)
    assert not p.sideboard and obj.zone==Zone.STACK
    eng.resolve_until_stable()
    assert obj in eng.state.battlefield and obj.zone==Zone.BATTLEFIELD
    assert p.mana_pool.total()==0


def test_land_and_opponent_permission_do_not_admit_cast():
    eng=engine([card(kind='Land')]);p=eng.state.players[0];obj=p.sideboard[0]
    permission(eng,'p2');p.mana_pool.add('C',10)
    assert not eng.can_cast(p,obj)
    permission(eng);assert not eng.can_cast(p,obj)
    assert not eng.can_play_land(p,obj)


def test_failed_cast_keeps_sideboard_and_sorcery_timing():
    eng=engine();p=eng.state.players[0];obj=p.sideboard[0];permission(eng)
    with pytest.raises(ValueError):eng.cast_spell(p,obj)
    assert p.sideboard==[obj] and obj.zone is None
    p.mana_pool.add('C',1);eng.state.current_step='upkeep'
    assert not eng.can_cast(p,obj)


def test_build_goldfish_loads_bound_outside_cards():
    eng=build_goldfish_engine([],starting_hand=0,sideboard=[card()])
    assert len(eng.state.players[0].sideboard)==1
    assert eng.state.players[0].to_dict()['sideboard'][0]['zone'] is None


def test_parser_does_not_claim_other_outside_permissions():
    assert match_clause(BODY)
    assert match_clause('you get an emblem with "you can cast land cards from your sideboard."') is None
    assert match_clause('you get an emblem with "you can cast nonland cards from your sideboard without paying their mana costs."') is None


def test_private_views_observers_and_undo_restore_same_outside_id():
    eng=engine();p=eng.state.players[0];permission(eng);p.mana_pool.add('C',1)
    session=GameSession(eng)
    iid=p.sideboard[0].instance_id
    assert session.view('p1')['state']['players'][0]['sideboard'][0]['instance_id']==iid
    assert session.view('p2')['state']['players'][0]['sideboard']==[]
    assert session.observer_view()['state']['players'][0]['sideboard']==[]
    session.apply_action({'type':'cast_spell','instance_id':iid},actor_id='p1')
    assert not eng.state.players[0].sideboard
    session.rewind()
    restored=session.engine.state.players[0].sideboard[0]
    assert restored.instance_id==iid and restored.zone is None


def test_turn_controller_gets_uniform_blind_slots_and_generic_error_then_can_cast():
    from mtg_analyzer.models.game.game_state import TurnControl
    eng=engine([card('Secret'),card('Unpayable',cost='{99}'),card('Land',kind='Land')])
    p=eng.state.players[0];permission(eng);p.mana_pool.add('C',1)
    control=TurnControl('p1','p2',eng.state.internal_turn.number,'turn','Mindslaver')
    control.phase='active';eng.state.turn_controls.append(control)
    session=GameSession(eng)
    view=session.view('p2');assert view['state']['players'][0]['sideboard']==[]
    blind=[a for a in view['legal_actions'] if a.get('blind_sideboard')]
    assert len(blind)==3 and all(set(a)=={'type','instance_id','blind_sideboard','name'} for a in blind)
    with pytest.raises(GameActionError,match='Sideboard casting announcement is not legal'):
        session.apply_action({'type':'cast_spell','instance_id':p.sideboard[1].instance_id},actor_id='p2')
    rejected_id=session.engine.state.players[0].sideboard[1].instance_id
    for encoded_id in [rejected_id, str(rejected_id), f'000{rejected_id}', f'+{rejected_id}']:
        with pytest.raises(GameActionError,match='Sideboard casting announcement is not legal'):
            session.apply_action({'type':'cast_spell','instance_id':encoded_id},actor_id='p2')
        assert len(session.engine.state.players[0].sideboard)==3
        assert session.engine.state.players[0].mana_pool.total()==1
    state=session.engine.state
    iid=state.players[0].sideboard[0].instance_id
    session.apply_action({'type':'cast_spell','instance_id':iid},actor_id='p2')
    assert session.engine.state.stack[-1].obj.name=='Secret'


def test_outside_object_id_cannot_be_targeted():
    eng=engine();session=GameSession(eng)
    with pytest.raises(GameActionError,match='outside the game'):
        session._resolve_targets([{'instance_id':eng.state.players[0].sideboard[0].instance_id}])


def test_instant_casts_at_opponents_turn_and_fake_membership_rejected():
    eng=engine([card(kind='Instant')]);p=eng.state.players[0];obj=p.sideboard[0];permission(eng)
    p.mana_pool.add('C',1);eng.state.active_player_index=1;eng.state.current_step='upkeep'
    assert eng.can_cast(p,obj)
    fake=GameObject(obj.card,owner_id=p.id,zone=None)
    assert not eng.can_cast(p,fake)
    eng.cast_spell(p,obj);eng.resolve_until_stable()
    assert obj in p.graveyard and not p.sideboard


def test_multiplayer_builder_attaches_each_owners_sideboard():
    from mtg_analyzer.services.game_session import build_multiplayer_engine
    eng=build_multiplayer_engine([{'player_id':'p1','library':[],'sideboard':[card('One')]},
                                  {'player_id':'p2','library':[],'sideboard':[card('Two')]}],starting_hand=0)
    assert [p.sideboard[0].owner_id for p in eng.state.players]==['p1','p2']


def test_mdfc_nonland_back_cast_from_land_front():
    dfc=card('Land Front',kind='Land',cost='')
    dfc.layout='modal_dfc';dfc.back_name='Creature Back';dfc.back_type_line='Creature';dfc.back_mana_cost_string='{1}'
    dfc.back_power=2;dfc.back_toughness=2
    eng=engine([dfc]);p=eng.state.players[0];obj=p.sideboard[0];permission(eng);p.mana_pool.add('C',1)
    assert not eng.can_cast(p,obj)
    assert eng.can_cast(p,obj,face='back')
    assert any(a.get('face')=='back' and a.get('instance_id')==obj.instance_id for a in eng.legal_actions(p))
    eng.cast_spell(p,obj,face='back');eng.resolve_until_stable()
    assert obj in eng.state.battlefield and obj.name=='Creature Back'


def test_targeted_instant_runs_actual_parser_effect():
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    spell=card('Outside Tap',kind='Instant');spell.oracle_text='Tap target creature.'
    eng=engine([spell]);p=eng.state.players[0];permission(eng);p.mana_pool.add('C',1)
    target=GameObject(card('Target'),owner_id='p2',zone=Zone.BATTLEFIELD);eng.state.add_to_battlefield(target)
    eng.cast_spell(p,p.sideboard[0],targets=[target]);eng.resolve_until_stable()
    assert target.tapped


def test_permission_is_live_and_hand_reveal_does_not_expose_sideboard():
    from mtg_analyzer.game.effects.core import StaticAbility
    eng=engine();p=eng.state.players[0];permission(eng);p.mana_pool.add('C',1)
    assert eng.can_cast(p,p.sideboard[0])
    p.emblems.clear()
    assert not eng.can_cast(p,p.sideboard[0])
    # Opponent's Inzerva-style emblem publicly reveals p1's hand only.
    src=GameObject(card('Inzerva','Enchantment','{0}'),owner_id='p2',zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(src)
    specs=match_clause('you get an emblem with "your opponents play with their hands revealed."')
    for effect in build_effects(specs,source=src):effect.apply(GameContext(eng.state,eng.rules))
    hand=GameObject(card('Public hand card'),owner_id='p1',zone=Zone.HAND);p.hand.append(hand)
    view=GameSession(eng).view('p2')['state']['players'][0]
    assert view['hand'][0]['name']=='Public hand card' and view['sideboard']==[]
    assert p.sideboard[0] not in eng.state.permanents()
    assert p.sideboard[0] not in p.library+p.hand+p.graveyard+p.exile+p.command



def test_rejected_unrelated_choice_preserves_live_engine_and_pending_frame():
    eng=engine();session=GameSession(eng)
    pending={'kind':'opponent_target','player_id':'p2',
             'options':[{'id':'decline','label':'Decline'}]}
    eng.state.pending_choice=pending
    with pytest.raises(GameActionError):
        session.apply_action({'type':'choose','option_id':'decline'},actor_id='p1')
    # Authorization failed before a choice was answered: preserve the live
    # engine and its original continuation, rather than rebuilding a snapshot.
    assert session.engine is eng
    assert eng.state.pending_choice is pending

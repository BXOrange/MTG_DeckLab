"""PAR-149: command-zone static emblem permissions and actual player choices."""
import pytest
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.game_status import CreateEmblemEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.emblem_statics import emblem_static_effect_specs
from mtg_analyzer.parser.oracle.spec import AbilitySpec

TEFERI="You may activate loyalty abilities of planeswalkers you control on any player's turn any time you could cast an instant."
NARSET="Your opponents can't cast noncreature spells."
DOVIN="Your opponents can't untap more than 2 permanents during their untap steps."


def game():
    return GameEngine.new_game([('p1','A',[]),('p2','B',[]),('p3','C',[])],starting_hand=0)


def board(engine,name,text='',pid='p1',**kw):
    card=Card(id=name,name=name,oracle_text=text,**kw)
    obj=GameObject(card,pid,Zone.BATTLEFIELD)
    engine.state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def emblem(engine,text):
    effects=emblem_static_effect_specs(text)
    assert effects
    payload=AbilitySpec('static',effects=effects,raw_text=text)
    payload.validate()
    source=board(engine,'Emblem Source',type_line='Planeswalker',loyalty=5)
    CreateEmblemEffect(ability=payload.to_dict(),source=source).apply(engine.rules.context)
    engine.rules.destroy(source)
    assert engine.state.players[0].emblems
    return engine.state.players[0].emblems[0]


def test_teferi_emblem_on_command_zone_permits_responding_loyalty_once_each_turn_only_for_its_controller():
    engine=game();p1,p2,p3=engine.state.players
    emblem(engine,TEFERI)
    ours=board(engine,'Our Walker','+1: You gain 1 life.',type_line='Planeswalker',loyalty=3)
    theirs=board(engine,'Their Walker','+1: You gain 1 life.',pid=p3.id,type_line='Planeswalker',loyalty=3)
    engine.start();engine.begin_turn()
    engine.state.current_phase='beginning';engine.state.current_step='upkeep'
    assert engine.state.active_player is p2
    assert engine.can_activate(p1,ours,ours.activated_abilities[0])
    assert not engine.can_activate(p3,theirs,theirs.activated_abilities[0])
    engine.activate_ability(p1,ours,0)
    assert not engine.can_activate(p1,ours,ours.activated_abilities[0])
    engine.resolve_until_stable()
    assert p1.life == 41
    engine.begin_turn()
    engine.state.current_phase='beginning';engine.state.current_step='upkeep'
    assert engine.can_activate(p1,ours,ours.activated_abilities[0])


@pytest.mark.parametrize('zone',[Zone.HAND,Zone.GRAVEYARD,Zone.EXILE])
def test_narset_command_zone_restricts_opponents_in_all_cast_zones_and_free_casts(zone):
    engine=game();p1,p2,p3=engine.state.players
    emblem(engine,NARSET)
    engine.state.current_step='main1';engine.state.current_phase='precombat_main'
    for player in [p1,p2,p3]:
        card=Card(id='s'+player.id,name='Instant',type_line='Instant',is_instant=True,mana_cost_string='{U}',oracle_text='Draw a card.\nFlashback {U}')
        card.keywords=['Flashback']
        obj=GameObject(card,player.id,zone);player.add_to_zone(obj,zone);bind_from_catalogue(obj)
        player.mana_pool.add('U',1)
        engine.state.free_cast_instance_ids.add(obj.instance_id)
        engine.state.free_cast_ignore_timing_instance_ids.add(obj.instance_id)
        if zone == Zone.EXILE:
            engine.rules.grant_free_cast_window_from_exile(obj,caster=player,ignore_timing=True)
        assert engine.can_cast(player,obj,free=zone != Zone.GRAVEYARD) == (player is p1)
    creature=GameObject(Card(id='bear',name='Bear',type_line='Creature',is_creature=True,power=2,toughness=2),p2.id,Zone.HAND)
    p2.add_to_zone(creature,Zone.HAND)
    engine.state.free_cast_instance_ids.add(creature.instance_id)
    engine.state.free_cast_ignore_timing_instance_ids.add(creature.instance_id)
    assert engine.can_cast(p2,creature,free=True)


def test_dovin_opponent_selects_two_permanents_before_any_untap_and_controller_is_uncapped():
    engine=game();p1,p2,p3=engine.state.players
    emblem(engine,DOVIN)
    ours=[board(engine,'Our'+str(i),type_line='Artifact') for i in range(3)]
    theirs=[board(engine,'Their'+str(i),pid=p2.id,type_line='Artifact') for i in range(4)]
    for obj in ours+theirs:obj.tapped=True
    engine.state.active_player_index=0
    engine._step_untap()
    assert not engine.state.pending_choice and all(not obj.tapped for obj in ours)
    engine.state.active_player_index=1
    engine._step_untap()
    assert engine.state.pending_choice['player_id'] == p2.id
    assert all(obj.tapped for obj in theirs)
    engine.resolve_pending_choice(str(theirs[3].instance_id))
    assert all(obj.tapped for obj in theirs)  # choices precede simultaneous untap
    engine.resolve_pending_choice(str(theirs[1].instance_id))
    assert not engine.state.pending_choice
    assert [obj.tapped for obj in theirs] == [True,False,True,False]


def test_dovin_choices_survive_state_clone_and_invalid_answer_does_not_auto_pick():
    engine=game();emblem(engine,DOVIN)
    objs=[board(engine,'Choice'+str(i),pid='p2',type_line='Artifact') for i in range(3)]
    for obj in objs:obj.tapped=True
    engine.state.active_player_index=1;engine._step_untap()
    engine.state=engine.state.clone();engine.rules.state=engine.state;engine.rules.context.state=engine.state
    with pytest.raises(ValueError):engine.resolve_pending_choice('not-a-permanent')
    assert engine.state.pending_choice['kind']=='untap_cap_selection'
    engine.resolve_pending_choice(str(objs[2].instance_id))
    engine.resolve_pending_choice(str(objs[0].instance_id))
    assert sum(not engine.state.find_object(obj.instance_id).tapped for obj in objs)==2

ELLYWICK="Creatures you control have trample and haste and get +2/+2 for each differently named dungeon you've completed."
INZERVA="Your opponents play with their hands revealed."
WRENN="You may play lands and cast permanent spells from your graveyard."
SERRA="If you control a creature, damage that would reduce your life total to less than 1 reduces it to 1 instead."


def test_ellywick_unique_dungeons_live_count_and_keywords():
    engine=game();p1=engine.state.players[0]
    emblem(engine,ELLYWICK)
    ours=board(engine,'Bear',type_line='Creature',is_creature=True,power=2,toughness=2)
    theirs=board(engine,'Other',pid='p2',type_line='Creature',is_creature=True,power=2,toughness=2)
    engine.recompute_continuous_effects()
    assert (ours.power,ours.toughness)==(2,2)
    assert {'trample','haste'} <= ours.granted_keywords
    p1.completed_dungeons.extend(['Lost Mine','Lost Mine','Tomb'])
    engine.recompute_continuous_effects()
    assert (ours.power,ours.toughness)==(6,6)
    assert (theirs.power,theirs.toughness)==(2,2)
    assert 'haste' not in theirs.granted_keywords


def test_serra_life_floor_is_conditional_and_only_changes_damage_life_consequence():
    engine=game();p1,p2,_=engine.state.players
    emblem(engine,SERRA)
    bear=board(engine,'Bear',type_line='Creature',is_creature=True,power=2,toughness=2)
    p1.life=4
    engine.rules.deal_damage(p1,9)
    assert p1.life==1
    engine.rules.lose_life(p1,1)
    assert p1.life==0
    p1.life=4
    engine.rules.destroy(bear)
    engine.rules.deal_damage(p1,9)
    assert p1.life==-5
    p2.life=4
    engine.rules.deal_damage(p2,9)
    assert p2.life==-5


def test_wrenn_permission_uses_existing_costs_timing_and_land_limits():
    from mtg_analyzer.game.graveyard_cast import graveyard_cast_grant_for,graveyard_land_play_grant_for
    engine=game();p1,p2,_=engine.state.players
    emblem(engine,WRENN)
    creature=Card(id='permanent',name='Bear',type_line='Creature',is_creature=True,power=2,toughness=2,mana_cost_string='{G}')
    land=Card(id='land',name='Land',type_line='Land',is_land=True)
    instant=Card(id='instant',name='Instant',type_line='Instant',is_instant=True)
    obj=GameObject(creature,p1.id,Zone.GRAVEYARD);p1.add_to_zone(obj,Zone.GRAVEYARD)
    assert graveyard_cast_grant_for(p1,engine.state,creature)
    assert graveyard_land_play_grant_for(p1,engine.state,land)
    assert not graveyard_cast_grant_for(p1,engine.state,instant)
    assert not graveyard_cast_grant_for(p2,engine.state,creature)
    engine.state.current_phase='precombat_main';engine.state.current_step='main1'
    assert not engine.can_cast(p1,obj)
    p1.mana_pool.add('G',1)
    assert engine.can_cast(p1,obj)
    engine.state.active_player_index=1
    assert not engine.can_cast(p1,obj)


def test_inzerva_reveals_only_opponents_hands_including_spectator():
    from mtg_analyzer.game.emblem_permissions import publicly_revealed_hand_ids
    from mtg_analyzer.services.game_session import _redact_hidden_zones
    engine=game();emblem(engine,INZERVA)
    revealed=publicly_revealed_hand_ids(engine.state)
    assert revealed=={'p2','p3'}
    for viewer in [None,'p1','p2','p3']:
        data={'players':[{'id':pid,'hand':[{'name':pid}], 'library':[{'name':'secret'}]} for pid in ['p1','p2','p3']]}
        _redact_hidden_zones(data,viewer,also_visible_hand_ids=revealed)
        for player in data['players']:
            assert bool(player['hand'])==(player['id'] in revealed or player['id']==viewer)
            assert not player['library']


def test_inzerva_session_view_and_observer_never_publish_libraries():
    from mtg_analyzer.services.game_session import GameSession
    engine=game();emblem(engine,INZERVA)
    for player in engine.state.players:
        for zone in [Zone.HAND,Zone.LIBRARY]:
            obj=GameObject(Card(id=player.id+zone.value,name='Secret '+player.id,type_line='Instant',is_instant=True),player.id,zone)
            player.add_to_zone(obj,zone)
    session=GameSession(engine)
    for viewer in ['p1','p2','p3',None]:
        view=session.observer_view() if viewer is None else session.view(perspective=viewer)
        for player in view['state']['players']:
            assert bool(player['hand']) == (player['id'] != 'p1' or viewer=='p1')
            assert not player['library']


def test_wrenn_actual_graveyard_land_play_and_spell_cast():
    engine=game();p1=engine.state.players[0]
    emblem(engine,WRENN)
    engine.state.current_phase='precombat_main';engine.state.current_step='main1'
    land=GameObject(Card(id='forest',name='Forest',type_line='Basic Land — Forest',is_land=True),p1.id,Zone.GRAVEYARD)
    bear=GameObject(Card(id='bear',name='Bear',type_line='Creature',is_creature=True,power=2,toughness=2,mana_cost_string='{G}'),p1.id,Zone.GRAVEYARD)
    second=GameObject(Card(id='land2',name='Forest',type_line='Basic Land — Forest',is_land=True),p1.id,Zone.GRAVEYARD)
    for obj in [land,bear,second]:p1.add_to_zone(obj,Zone.GRAVEYARD)
    assert engine.can_play_land(p1,land)
    engine.play_land(p1,land)
    assert land.zone==Zone.BATTLEFIELD
    assert not engine.can_play_land(p1,second)
    p1.mana_pool.add('G',1)
    engine.cast_spell(p1,bear)
    engine.resolve_until_stable()
    assert bear.zone==Zone.BATTLEFIELD
    assert p1.mana_pool.total()==0


def test_dovin_stun_selection_consumes_slot_and_does_not_offer_extra_untap():
    engine=game();emblem(engine,DOVIN)
    objs=[board(engine,'Stun'+str(i),pid='p2',type_line='Artifact') for i in range(3)]
    for obj in objs:obj.tapped=True
    objs[0].counters['stun']=1
    engine.state.active_player_index=1;engine._step_untap()
    engine.resolve_pending_choice(str(objs[0].instance_id))
    engine.resolve_pending_choice(str(objs[1].instance_id))
    assert not engine.state.pending_choice
    assert objs[0].tapped and objs[0].counters.get('stun',0)==0
    assert not objs[1].tapped and objs[2].tapped


@pytest.mark.parametrize('text',[
    "Your opponents play with their hands and libraries revealed.",
    "You may play lands and cast spells from your opponents' graveyards.",
    "If you control a creature, you can't lose life.",
    "Creatures you control have trample and haste and get +2/+2 for each dungeon you've completed.",
])
def test_static_emblem_grammar_rejects_nearby_unsupported_shapes(text):
    assert emblem_static_effect_specs(text) is None


def test_serra_damage_dealt_is_not_prevented():
    engine=game();p1,p2,_=engine.state.players
    emblem(engine,SERRA)
    board(engine,'Our creature',type_line='Creature',is_creature=True,power=2,toughness=2)
    source=board(engine,'Lifelinker',pid='p2',type_line='Creature',is_creature=True,power=9,toughness=9,keywords=['Lifelink'])
    engine.recompute_continuous_effects()
    p1.life=4;p2.life=10
    engine.rules.deal_damage(p1,9,source=source)
    assert p1.life==1
    events=[event for event in engine.state.events_this_turn() if event.type=='DAMAGE']
    assert events[-1].get('amount')==9

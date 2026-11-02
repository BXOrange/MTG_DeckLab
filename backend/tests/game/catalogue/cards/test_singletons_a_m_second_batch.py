"""The second singleton batch executes event, flip, and Battle abilities."""
import pytest
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.card_registry import _REGISTRY, specs_for
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType,GameEvent
from mtg_analyzer.models.game.game_object import GameObject,Zone
from tests.support.catalogue import battlefield_object,two_player_game


def put(engine,p,name,typ='Creature',**kwargs):
    obj=battlefield_object(engine,p,name,typ,**kwargs)
    bind_from_catalogue(obj)
    return obj


def run(engine,source,index,targets=()):
    context=GameContext(engine.state,engine.rules)
    for effect in build_effects(_REGISTRY[source.name.lower()]()[index].effects,source):
        effect.apply(context,list(targets))


def test_custodi_lich_crown_change_fires_edict_but_repeated_designation_does_not():
    engine,p=two_player_game()
    lich=put(engine,p.id,'Custodi Lich',is_creature=True,power=4,toughness=2)
    victim=put(engine,'p2','Victim',is_creature=True,power=2,toughness=2)
    engine.rules.become_monarch(p)
    engine.resolve_until_stable()
    assert engine.state.pending_choice['kind']=='trigger_target'
    engine.resolve_pending_choice('p2')
    engine.resolve_until_stable()
    if engine.state.pending_choice:
        engine.resolve_pending_choice(str(victim.instance_id))
        engine.resolve_until_stable()
    assert victim.zone==Zone.GRAVEYARD
    before=sum(e.type==EventType.BECAME_MONARCH for e in engine.state.event_log)
    engine.rules.become_monarch(p)
    assert sum(e.type==EventType.BECAME_MONARCH for e in engine.state.event_log)==before


def test_ezuri_experience_enters_and_combat_counters():
    engine,p=two_player_game()
    ezuri=put(engine,p.id,'Ezuri, Claw of Progress',is_creature=True,power=3,toughness=3)
    small=put(engine,p.id,'Small',is_creature=True,power=2,toughness=2)
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD,instance_id=small.instance_id,controller_id=p.id,object_types=['creature'],object_power=2))
    engine.resolve_until_stable()
    assert p.counters.get('experience')==1
    p.counters['experience']=3
    run(engine,ezuri,1,[small])
    assert small.counters.get('+1/+1')==3
    assert not ezuri.counters


@pytest.mark.parametrize('land_count,hand_land,flips', [(9,True,True),(10,False,True),(9,False,False)])
def test_budoka_front_activation_places_land_then_checks_flip(land_count,hand_land,flips):
    engine,p=two_player_game()
    card=Card(id='budoka',name='Budoka Gardener // Dokai, Weaver of Life',type_line='Creature — Human Monk',is_creature=True,power=2,toughness=1,layout='flip',back_name='Dokai, Weaver of Life',back_type_line='Legendary Creature — Human Monk',back_power=3,back_toughness=3,back_oracle_text='{4}{G}{G}, {T}: Create an X/X green Elemental creature token, where X is the number of lands you control.')
    source=GameObject(card,owner_id=p.id,zone=Zone.BATTLEFIELD);engine.state.add_to_battlefield(source);bind_from_catalogue(source)
    source.summoning_sick=False
    for i in range(land_count): put(engine,p.id,f'Land{i}','Land',is_land=True)
    if hand_land:
        land=GameObject(Card(id='handland',name='Handland',type_line='Land',is_land=True),owner_id=p.id,zone=Zone.HAND)
        p.add_to_zone(land,Zone.HAND)
    engine.activate_ability(p,source,0)
    engine.resolve_until_stable()
    if engine.state.pending_choice:
        assert hand_land
        opt=next(o for o in engine.state.pending_choice['options'] if o.get('instance_id')==land.instance_id)
        engine.resolve_pending_choice(opt['id'])
        engine.resolve_until_stable()
        assert land in engine.state.battlefield
    assert (source.name=='Dokai, Weaver of Life') is flips
    if flips:
        assert len(source.activated_abilities)==1
        run(engine,source,0)
        token=next(o for o in engine.state.battlefield if o.is_token)
        assert token.name=='Elemental' and (token.power,token.toughness)==(10,10)


def test_invasion_azgol_opponent_chooses_planeswalker_and_loses_life():
    engine,p=two_player_game();enemy=engine.state.player_by_id('p2')
    siege=put(engine,p.id,'Invasion of Azgol','Battle — Siege')
    walker=put(engine,'p2','Walker','Planeswalker')
    run(engine,siege,0,[enemy])
    if engine.state.pending_choice: engine.resolve_pending_choice(str(walker.instance_id))
    assert walker.zone==Zone.GRAVEYARD
    assert enemy.life==19 and p.life==20


def test_ashen_reaper_only_counts_battlefield_to_graveyard_this_turn():
    engine,p=two_player_game()
    reaper=put(engine,p.id,'Ashen Reaper',is_creature=True,power=2,toughness=2)
    run(engine,reaper,0)
    assert not reaper.counters
    enemy=put(engine,'p2','Enemy','Creature',is_creature=True,power=2,toughness=2)
    engine.rules.sacrifice(engine.state.player_by_id('p2'),'creature',1)
    if engine.state.pending_choice:engine.resolve_pending_choice(str(enemy.instance_id))
    run(engine,reaper,0)
    assert reaper.counters.get('+1/+1')==1


@pytest.mark.parametrize('name', ['Custodi Lich','Ezuri, Claw of Progress','Budoka Gardener','Dokai, Weaver of Life','Invasion of Azgol','Ashen Reaper','Invasion of Theros'])
def test_fresh_specs_bind(name):
    card=Card(id=name,name=name,type_line='Creature',is_creature=True)
    a,b=specs_for(card),specs_for(card)
    assert a and all(x is not y for x,y in zip(a,b))
    obj=GameObject(card,owner_id='p1',zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    assert obj.activated_abilities or obj.triggered_abilities


def test_invasion_theros_searches_god_or_demigod_or_aura():
    engine,p=two_player_game();siege=put(engine,p.id,'Invasion of Theros','Battle — Siege')
    for name,typ in [('God','Enchantment Creature — God'),('Demigod','Creature — Demigod'),('Aura','Enchantment — Aura'),('Bear','Creature — Bear')]:
        obj=GameObject(Card(id=name,name=name,type_line=typ),owner_id=p.id,zone=Zone.LIBRARY)
        p.add_to_zone(obj,Zone.LIBRARY)
    run(engine,siege,0)
    options=engine.state.pending_choice['options']
    assert {o['label'] for o in options if not o.get('decline')} >= {'God','Demigod','Aura'}
    assert not any(o['label']=='Bear' for o in options)


def test_ezuri_combat_trigger_only_during_controllers_combat():
    engine,p=two_player_game()
    source=put(engine,p.id,'Ezuri, Claw of Progress',is_creature=True,power=3,toughness=3)
    target=put(engine,p.id,'Other',is_creature=True,power=2,toughness=2)
    p.counters['experience']=2
    engine.state.active_player_index=1
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN,step='begin_combat',player_id='p2'))
    engine.resolve_until_stable()
    assert not engine.state.pending_choice and not target.counters
    engine.state.active_player_index=0
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN,step='begin_combat',player_id=p.id))
    engine.resolve_until_stable()
    assert engine.state.pending_choice['kind']=='trigger_target'
    assert source.instance_id not in [o.get('instance_id') for o in engine.state.pending_choice['options']]
    engine.resolve_pending_choice(str(target.instance_id));engine.resolve_until_stable()
    assert target.counters['+1/+1']==2

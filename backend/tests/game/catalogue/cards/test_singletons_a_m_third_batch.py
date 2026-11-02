"""Life-scaled cost and half-stat singleton abilities execute through the engine."""
import pytest
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.continuous import cost_reduction_for,self_cost_reduction_for
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject,Zone
from mtg_analyzer.models.game.events import EventType,GameEvent
from tests.support.catalogue import battlefield_object,two_player_game


def put(engine,player,name,typ='Creature',**kwargs):
    obj=battlefield_object(engine,player,name,typ,**kwargs)
    bind_from_catalogue(obj)
    obj.summoning_sick=False
    return obj


def test_ezzaroot_scales_only_your_creature_spells_and_tap_gains_life():
    engine,p=two_player_game()
    source=put(engine,p.id,'Ezzaroot Channeler',is_creature=True,power=4,toughness=4)
    creature=put(engine,p.id,'Bear',is_creature=True,power=2,toughness=2)
    other=put(engine,p.id,'Spell','Sorcery',is_sorcery=True)
    assert cost_reduction_for(engine.state,p,creature)[0]==0
    engine.activate_ability(p,source);engine.resolve_until_stable()
    assert p.life==22
    assert cost_reduction_for(engine.state,p,creature)[0]==2
    assert cost_reduction_for(engine.state,p,other)[0]==0
    assert cost_reduction_for(engine.state,engine.state.player_by_id('p2'),creature)[0]==0


def test_licia_scales_self_discount_and_preserves_once_per_turn_activation():
    engine,p=two_player_game()
    licia=put(engine,p.id,'Licia, Sanguine Tribune',is_creature=True,power=4,toughness=4)
    assert self_cost_reduction_for(licia,engine.state)[0]==0
    engine.rules.gain_life(p,5)
    assert self_cost_reduction_for(licia,engine.state)[0]==5
    engine.activate_ability(p,licia);engine.resolve_until_stable()
    assert licia.counters['+1/+1']==3 and p.life==20
    with pytest.raises(ValueError):engine.activate_ability(p,licia)


@pytest.mark.parametrize('life1,life2,left1,left2',[(21,11,11,6),(20,8,10,4),(1,1,1,1)])
def test_heartless_each_player_measures_their_own_life_rounding_down(life1,life2,left1,left2):
    engine,p=two_player_game();other=engine.state.player_by_id('p2')
    p.life=life1;other.life=life2
    source=put(engine,p.id,'Heartless Hidetsugu',is_creature=True,power=4,toughness=3)
    engine.activate_ability(p,source);engine.resolve_until_stable()
    assert (p.life,other.life)==(left1,left2)


@pytest.mark.parametrize('color,valid', [('R',True),('W',True),('U',False)])
def test_freyalise_sacrifices_only_red_or_white_creature_and_deals_half_power(color,valid):
    engine,p=two_player_game();enemy=engine.state.player_by_id('p2')
    source=put(engine,p.id,'Freyalise Supplicant',is_creature=True,power=1,toughness=1)
    victim=put(engine,p.id,'Victim',is_creature=True,power=5,toughness=5,color_identity={color})
    if valid:
        engine.activate_ability(p,source,targets=[enemy],sacrifice_choice=victim.instance_id)
        assert victim.zone==Zone.GRAVEYARD
        engine.resolve_until_stable();assert enemy.life==18
    else:
        with pytest.raises(ValueError):engine.activate_ability(p,source,targets=[enemy],sacrifice_choice=victim.instance_id)
        assert victim.zone==Zone.BATTLEFIELD and enemy.life==20


def test_freyalise_rejects_red_noncreature():
    engine,p=two_player_game();enemy=engine.state.player_by_id('p2')
    source=put(engine,p.id,'Freyalise Supplicant',is_creature=True,power=1,toughness=1)
    victim=put(engine,p.id,'Red rock','Artifact',color_identity={'R'})
    with pytest.raises(ValueError):engine.activate_ability(p,source,targets=[enemy],sacrifice_choice=victim.instance_id)


@pytest.mark.parametrize('typ,related,reduced', [('Creature — Bear',True,True),('Artifact Creature — Bear',True,False),('Creature — Dragon',True,False),('Creature — Bear',False,False)])
def test_catacomb_only_reduces_nonartifact_nondragon_creature_blocking_it(typ,related,reduced):
    engine,p=two_player_game()
    dragon=put(engine,p.id,'Catacomb Dragon',is_creature=True,power=4,toughness=4)
    another=put(engine,p.id,'Another attacker',is_creature=True,power=2,toughness=2)
    blocker=put(engine,'p2','Blocker',typ,is_creature=True,power=5,toughness=5)
    engine.state.fire_event(GameEvent(EventType.BLOCKS,instance_id=blocker.instance_id,controller_id='p2',related_ids=[(dragon if related else another).instance_id],object_types=sorted(blocker.type_words)))
    engine.resolve_until_stable();engine.recompute_continuous_effects()
    assert blocker.power==(3 if reduced else 5)
    assert blocker.toughness==5


@pytest.mark.parametrize('name', ['Ezzaroot Channeler','Licia, Sanguine Tribune','Heartless Hidetsugu','Freyalise Supplicant','Catacomb Dragon'])
def test_specs_are_fresh_and_bind(name):
    c=Card(id=name,name=name,type_line='Creature',is_creature=True)
    a,b=specs_for(c),specs_for(c)
    assert a and all(x is not y for x,y in zip(a,b))
    obj=GameObject(c,owner_id='p1',zone=Zone.BATTLEFIELD);bind_from_catalogue(obj)
    assert obj.activated_abilities or obj.triggered_abilities


def test_freyalise_uses_modified_sacrificed_power_last_known_information():
    engine,p=two_player_game();enemy=engine.state.player_by_id('p2')
    source=put(engine,p.id,'Freyalise Supplicant',is_creature=True,power=1,toughness=1)
    victim=put(engine,p.id,'Victim',is_creature=True,power=3,toughness=3,color_identity={'R'})
    engine.rules.add_counters(victim,2,'+1/+1')
    engine.activate_ability(p,source,targets=[enemy],sacrifice_choice=victim.instance_id)
    engine.resolve_until_stable()
    assert enemy.life==18


def test_heartless_lifelink_damage_is_one_simultaneous_instruction_even_on_opponents_turn():
    engine,p=two_player_game();enemy=engine.state.player_by_id('p2')
    source=put(engine,p.id,'Heartless Hidetsugu',is_creature=True,power=4,toughness=3)
    source.temp_keywords.add('lifelink')
    engine.state.active_player_index=1
    engine.activate_ability(p,source);engine.resolve_until_stable()
    assert enemy.life==10 and p.life==30
    damage=[e.get('amount') for e in engine.state.event_log if e.type==EventType.DAMAGE]
    assert damage==[10,10]
    gains=[e.get('amount') for e in engine.state.event_log if e.type==EventType.LIFE_GAINED]
    assert gains==[20]

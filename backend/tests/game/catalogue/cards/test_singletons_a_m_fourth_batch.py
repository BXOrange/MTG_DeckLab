"""Flip, Room and turn-history singleton behavior through live game actions."""
import pytest
from mtg_analyzer.game import rooms
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import specs_for,is_authored_card
from mtg_analyzer.game.continuous import granted_help_pay_keyword
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType,GameEvent
from mtg_analyzer.models.game.game_object import GameObject,Zone
from tests.support.catalogue import battlefield_object,two_player_game


def put(engine,p,name,typ='Creature',**kw):
    obj=battlefield_object(engine,p,name,typ,**kw);bind_from_catalogue(obj);obj.summoning_sick=False
    return obj


def zone_card(engine,p,name,zone=Zone.LIBRARY,typ='Creature',**kw):
    card=Card(id=name,name=name,type_line=typ,**kw);obj=GameObject(card,owner_id=p,zone=zone)
    engine.state.player_by_id(p).add_to_zone(obj,zone);bind_from_catalogue(obj)
    return obj


def room(engine,name,back):
    c=Card(id=name,name=name+' // '+back,type_line='Enchantment — Room',layout='split',back_name=back,back_type_line='Enchantment — Room',mana_cost_string='{2}{W}',back_mana_cost_string='{3}{W}')
    obj=GameObject(c,owner_id='p1',zone=Zone.BATTLEFIELD);engine.state.add_to_battlefield(obj);bind_from_catalogue(obj)
    assert is_authored_card(c)
    return obj


def test_erayo_counts_four_spells_across_players_and_flips_even_if_fifth_precedes_resolution():
    engine,p=two_player_game()
    c=Card(id='erayo',name="Erayo, Soratami Ascendant // Erayo's Essence",type_line='Legendary Creature — Moonfolk Monk',is_creature=True,power=1,toughness=1,layout='flip',oracle_text='Flying\nWhenever the fourth spell of a turn is cast, flip Erayo.',back_name="Erayo's Essence",back_type_line='Legendary Enchantment',back_oracle_text='Whenever an opponent casts their first spell each turn, counter that spell.')
    source=GameObject(c,owner_id=p.id,zone=Zone.BATTLEFIELD);engine.state.add_to_battlefield(source);bind_from_catalogue(source)
    for i in range(3):
        engine.state.fire_event(GameEvent(EventType.SPELL_CAST,player_id='p1' if i%2 else 'p2',instance_id=100+i))
        engine.resolve_until_stable()
        assert not source.flipped
    engine.state.fire_event(GameEvent(EventType.SPELL_CAST,player_id='p2',instance_id=104))
    engine.state.fire_event(GameEvent(EventType.SPELL_CAST,player_id='p1',instance_id=105))
    engine.resolve_until_stable()
    assert source.flipped and source.name=="Erayo's Essence"
    assert source.triggered_abilities


@pytest.mark.parametrize('cost',['{1}','{G}'])
def test_dazzling_creature_only_convoke_unlocks_and_relocks(cost):
    engine,p=two_player_game();engine.state.current_step='main1'
    source=room(engine,'Dazzling Theater','Prop Room')
    helper=put(engine,p.id,'Helper',is_creature=True,power=2,toughness=2,color_identity={'G'})
    spell=zone_card(engine,p.id,'Bear',Zone.HAND,is_creature=True,power=2,toughness=2,mana_cost_string=cost)
    other=zone_card(engine,p.id,'Other',Zone.HAND,typ='Sorcery',is_sorcery=True,mana_cost_string='{G}')
    assert granted_help_pay_keyword(engine.state,spell) is None
    rooms.unlock(engine.state,source,'left')
    assert granted_help_pay_keyword(engine.state,spell)=='convoke'
    assert granted_help_pay_keyword(engine.state,other) is None
    assert engine.can_cast(p,spell,help_pay=True)
    engine.cast_spell(p,spell,help_pay=True);engine.resolve_until_stable()
    assert spell.zone==Zone.BATTLEFIELD and helper.tapped
    rooms.lock(engine.state,source,'left')
    assert granted_help_pay_keyword(engine.state,spell) is None


def test_prop_room_untaps_only_your_creatures_on_other_players_untap():
    engine,p=two_player_game();source=room(engine,'Dazzling Theater','Prop Room')
    own=put(engine,p.id,'Own',is_creature=True,power=2,toughness=2);rock=put(engine,p.id,'Rock','Artifact')
    enemy=put(engine,'p2','Enemy',is_creature=True,power=2,toughness=2)
    own.tapped=rock.tapped=enemy.tapped=True
    engine.state.active_player_index=1
    engine._step_untap()
    assert own.tapped and rock.tapped and not enemy.tapped
    rooms.unlock(engine.state,source,'right');engine._step_untap()
    assert not own.tapped and rock.tapped


def test_porcelain_gallery_is_live_base_pt_only_when_right_door_unlocked():
    engine,p=two_player_game();source=room(engine,"Dollmaker's Shop",'Porcelain Gallery')
    first=put(engine,p.id,'First',is_creature=True,power=5,toughness=6)
    other=put(engine,'p2','Enemy',is_creature=True,power=4,toughness=4)
    rooms.unlock(engine.state,source,'left');engine.recompute_continuous_effects()
    assert first.power==5
    rooms.unlock(engine.state,source,'right');engine.recompute_continuous_effects()
    assert (first.power,first.toughness)==(1,1) and other.power==4
    put(engine,p.id,'Second',is_creature=True,power=1,toughness=1);engine.rules.add_counters(first,1,'+1/+1');engine.recompute_continuous_effects()
    assert (first.power,first.toughness)==(3,3)
    rooms.lock(engine.state,source,'right');engine.recompute_continuous_effects()
    assert (first.power,first.toughness)==(6,7)


def test_greenhouse_gazebo_recovers_up_to_two_only_from_its_exact_mill_batch():
    engine,p=two_player_game();source=room(engine,'Greenhouse','Rickety Gazebo')
    old=zone_card(engine,p.id,'Old card',Zone.GRAVEYARD)
    for name,typ in [('Land','Land'),('Bear','Creature'),('Instant','Instant'),('Artifact','Artifact')]:zone_card(engine,p.id,name,typ=typ,is_creature=typ=='Creature')
    rooms.unlock(engine.state,source,'right');engine.resolve_until_stable()
    assert engine.state.pending_choice['kind']=='choose_objects'
    labels={o['label'] for o in engine.state.pending_choice['options']}
    assert 'Old card' not in labels and 'Instant' not in labels
    choices=[o for o in engine.state.pending_choice['options'] if o.get('instance_id')]
    engine.resolve_pending_choice(choices[0]['id'])
    if engine.state.pending_choice:
        choices=[o for o in engine.state.pending_choice['options'] if o.get('instance_id')]
        engine.resolve_pending_choice(choices[0]['id'])
    engine.resolve_until_stable()
    assert len(p.hand)==2 and old in p.graveyard


def test_bonecache_graveyard_exit_threshold_uses_only_your_graveyard():
    engine,p=two_player_game();source=put(engine,p.id,'Bonecache Overseer',is_creature=True,power=1,toughness=1)
    zone_card(engine,p.id,'Drawn')
    with pytest.raises(ValueError):engine.activate_ability(p,source)
    for i in range(3):engine.rules.exile(zone_card(engine,'p2',f'Enemy grave{i}',Zone.GRAVEYARD))
    with pytest.raises(ValueError):engine.activate_ability(p,source)
    for i in range(2):engine.rules.exile(zone_card(engine,p.id,f'Own grave{i}',Zone.GRAVEYARD))
    with pytest.raises(ValueError):engine.activate_ability(p,source)
    engine.rules.exile(zone_card(engine,p.id,'Third',Zone.GRAVEYARD))
    engine.activate_ability(p,source);engine.resolve_until_stable()
    assert p.life==19 and len(p.hand)==1


def test_bonecache_food_sacrifice_alternative_does_not_accept_destroyed_food():
    engine,p=two_player_game();source=put(engine,p.id,'Bonecache Overseer',is_creature=True,power=1,toughness=1)
    zone_card(engine,p.id,'Drawn')
    food=put(engine,p.id,'Food','Artifact — Food')
    engine.rules.destroy(food)
    with pytest.raises(ValueError):engine.activate_ability(p,source)
    food2=put(engine,p.id,'Food2','Artifact — Food')
    engine.rules.put_into_graveyard(food2)
    engine.activate_ability(p,source);engine.resolve_until_stable()
    assert len(p.hand)==1


@pytest.mark.parametrize('name', ['Erayo, Soratami Ascendant','Dazzling Theater','Prop Room',"Dollmaker's Shop",'Porcelain Gallery','Greenhouse','Rickety Gazebo','Bonecache Overseer'])
def test_fresh_half_specs(name):
    c=Card(id=name,name=name,type_line='Creature')
    a,b=specs_for(c),specs_for(c)
    assert a and all(x is not y for x,y in zip(a,b))

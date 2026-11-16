"""Tomb of Urami pays every controlled land and has an Ogre-conditional mana rider."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card,filler,game,main_phase


def board():
    engine=game(players=3,library=30)
    source=card(engine,'Tomb of Urami')
    player=engine.state.players[0]
    player.mana_pool.add_many({'B':2,'C':2})
    main_phase(engine)
    return engine,source,player


def activate(engine,source):
    engine.activate_ability(engine.state.players[0],source,0)


def tokens(engine):
    return [obj for obj in engine.state.battlefield if obj.name=='Urami']


def test_fresh_specs_and_bound_ability():
    engine,source,player=board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(source.activated_abilities)==1 and source.activated_abilities[0].cost.sacrifice_all_lands


def test_all_controlled_lands_are_paid_before_creating_token():
    engine,source,player=board()
    other=card(engine,'Forest')
    other.tapped=True
    foreign=card(engine,'Forest',player='p2')
    artifact=filler(engine,'Artifact',type_line='Artifact')
    activate(engine,source)
    assert source.zone==other.zone==Zone.GRAVEYARD and not tokens(engine)
    assert foreign.zone==artifact.zone==Zone.BATTLEFIELD
    assert player.mana_pool.total()==0
    engine.resolve_until_stable()
    token,=tokens(engine)
    assert token.is_token and token.card.is_legendary and token.power==token.toughness==5
    assert token.colors=={'B'} and combat.has(token,'flying')
    from mtg_analyzer.game import continuous
    assert all(continuous.has_subtype(token, subtype) for subtype in ('Demon','Spirit'))


def test_only_tomb_still_sacrifices_itself():
    engine,source,player=board()
    activate(engine,source)
    engine.resolve_until_stable()
    assert source.zone==Zone.GRAVEYARD and len(tokens(engine))==1


def test_cannot_sacrifice_one_land_blocks_entire_activation():
    engine,source,player=board()
    other=card(engine,'Forest')
    other.cant_be_sacrificed_this_turn=True
    with pytest.raises(ValueError):activate(engine,source)
    assert source.zone==other.zone==Zone.BATTLEFIELD and not source.tapped
    assert player.mana_pool.total()==4


def test_cannot_sacrifice_source_blocks_activation():
    engine,source,player=board()
    source.cant_be_sacrificed_this_turn=True
    with pytest.raises(ValueError):activate(engine,source)
    assert not source.tapped


def test_insufficient_mana_does_not_sacrifice_or_tap():
    engine,source,player=board()
    player.mana_pool.empty()
    with pytest.raises(ValueError):activate(engine,source)
    assert source.zone==Zone.BATTLEFIELD and not source.tapped


def test_countering_does_not_refund_lands_or_create_token():
    engine,source,player=board()
    activate(engine,source)
    engine.rules.counter_ability(engine.state.stack[-1])
    engine.resolve_until_stable()
    assert source.zone==Zone.GRAVEYARD and not tokens(engine)


def test_clone_keeps_paid_lands_and_pending_token():
    engine,source,player=board()
    activate(engine,source)
    restored=GameEngine(engine.state.clone())
    restored.resolve_until_stable()
    assert len(tokens(restored))==1 and not tokens(engine)
    assert restored.state.find_object(source.instance_id).zone==Zone.GRAVEYARD


def test_animated_land_is_also_sacrificed():
    engine,source,player=board()
    animated=filler(engine,'Animated land',type_line='Land Creature — Forest',power=2,toughness=2)
    activate(engine,source)
    assert animated.zone==Zone.GRAVEYARD


def test_mana_adds_black_and_deals_damage_without_ogre():
    engine,source,player=board()
    player.mana_pool.empty()
    engine.tap_for_mana(player,source)
    assert player.life==19 and player.mana_pool.to_dict()['B']==1 and not engine.state.stack
    assert any(e.type==EventType.DAMAGE and e.get('source_id')==source.instance_id for e in engine.state.events_this_turn())


@pytest.mark.parametrize('kind',['Creature — Ogre','Kindred Artifact — Ogre'])
def test_controlled_ogre_prevents_mana_rider_damage(kind):
    engine,source,player=board()
    filler(engine,'Ogre',type_line=kind,**({'power':3,'toughness':3} if kind.startswith('Creature') else {}))
    engine.tap_for_mana(player,source)
    assert player.life==20


def test_opponents_ogre_does_not_protect_controller():
    engine,source,player=board()
    filler(engine,'Ogre',type_line='Creature — Ogre',player='p2',power=3,toughness=3)
    engine.tap_for_mana(player,source)
    assert player.life==19


def test_condition_is_rechecked_for_each_mana_activation():
    engine,source,player=board()
    ogre=filler(engine,'Ogre',type_line='Creature — Ogre',power=3,toughness=3)
    engine.tap_for_mana(player,source)
    engine.rules.exile(ogre)
    source.tapped=False
    engine.tap_for_mana(player,source)
    assert player.life==19


def test_copied_mana_ability_rechecks_ogre_without_repaying_tap():
    from mtg_analyzer.game.effects.copied_mana_ability import CopiedManaAbilityEffect
    from mtg_analyzer.game.mana_abilities import mana_abilities_for
    engine,source,player=board()
    ability=mana_abilities_for(source)[0]
    copied=CopiedManaAbilityEffect(source,ability,source.zone_incarnation,0,0,0)
    source.tapped=True
    copied.apply(engine.rules.context)
    assert player.life==19
    filler(engine,'Ogre',type_line='Creature — Ogre',power=3,toughness=3)
    copied.apply(engine.rules.context)
    assert player.life==19 and source.tapped


def test_sacrificed_stolen_land_goes_to_its_owner():
    engine,source,player=board()
    land=card(engine,'Forest',player='p2')
    land.controller_id='p1'
    activate(engine,source)
    assert land in engine.state.players[1].graveyard


def test_summoning_sick_noncreature_land_can_activate():
    engine,source,player=board()
    source.summoning_sick=True
    activate(engine,source)
    engine.resolve_until_stable()
    assert len(tokens(engine))==1


def test_auto_taps_other_lands_for_mana_before_sacrificing_all():
    engine,source,player=board()
    player.mana_pool.empty()
    lands=[filler(engine,f'Swamp {i}',type_line='Land — Swamp') for i in range(4)]
    activate(engine,source)
    assert all(obj.zone==Zone.GRAVEYARD for obj in [source,*lands])
    engine.resolve_until_stable()
    assert len(tokens(engine))==1


def test_actual_land_play_then_activation():
    engine=game(players=3,library=30)
    main_phase(engine)
    source=card(engine,'Tomb of Urami',zone=Zone.HAND)
    player=engine.state.players[0]
    engine.play_land(player,source)
    player.mana_pool.add_many({'B':2,'C':2})
    activate(engine,source)
    engine.resolve_until_stable()
    assert source.zone==Zone.GRAVEYARD and len(tokens(engine))==1

"""Ambulatory Reactor's real mana abilities enforce both permitted uses."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.mana_abilities import mana_abilities_for
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game
from tests.support.star_trek import advance_to


def board():
    engine=game(players=3,library=20); advance_to(engine,'main1')
    reactor=card(engine,'Ambulatory Reactor')
    ally=filler(engine,'Mana creature',type_line='Artifact Creature',power=2,toughness=2)
    player=engine.state.player_by_id('p1')
    return engine,reactor,ally,player


def tap(engine,ally,player):
    engine.tap_for_mana(player,ally)


def test_fresh_specs_and_correct_recipients():
    engine,reactor,ally,player=board()
    a,b=specs_for(reactor.card),specs_for(reactor.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(mana_abilities_for(reactor,engine.state))==1
    assert len(mana_abilities_for(ally,engine.state))==1
    for obj in [filler(engine,'Plain',power=2,toughness=2),
                filler(engine,'Rock',type_line='Artifact'),
                filler(engine,'Enemy',player='p2',type_line='Artifact Creature',power=2,toughness=2)]:
        assert not mana_abilities_for(obj,engine.state)


@pytest.mark.parametrize('creature',[False,True])
def test_restricted_mana_casts_artifact_spells(creature):
    engine,reactor,ally,player=board(); tap(engine,ally,player)
    spell=filler(engine,'Artifact spell',type_line='Artifact Creature' if creature else 'Artifact',
                 power=1 if creature else None,toughness=1 if creature else None,mv=1,zone=Zone.HAND)
    assert engine.can_cast(player,spell)
    engine.cast_spell(player,spell); engine.resolve_until_stable()
    assert spell.zone==Zone.BATTLEFIELD


def test_restricted_mana_cannot_cast_nonartifact_spell():
    engine,reactor,ally,player=board(); tap(engine,ally,player)
    spell=filler(engine,'Plain creature',power=1,toughness=1,mv=1,zone=Zone.HAND)
    assert not engine.can_cast(player,spell)
    with pytest.raises(ValueError):
        engine.cast_spell(player,spell)
    assert spell.zone==Zone.HAND


@pytest.mark.parametrize('artifact',[False,True])
def test_only_artifact_source_activations_can_use_the_mana(artifact):
    engine,reactor,ally,player=board(); tap(engine,ally,player)
    source=filler(engine,'Ability source',type_line='Artifact Creature' if artifact else 'Creature',
                  power=2,toughness=2,oracle_text='{1}: Draw a card.')
    ability=source.activated_abilities[0]
    assert engine.can_activate(player,source,ability)==artifact
    before=len(player.hand)
    if artifact:
        engine.activate_ability(player,source,0); engine.resolve_until_stable()
        assert len(player.hand)==before+1
    else:
        with pytest.raises(ValueError):
            engine.activate_ability(player,source,0)
        assert len(player.hand)==before


def test_summoning_sickness_prevents_using_granted_tap_ability():
    engine,reactor,ally,player=board(); ally.summoning_sick=True
    with pytest.raises(ValueError):
        tap(engine,ally,player)
    assert not ally.tapped


def test_reactor_departure_ends_grant_but_not_already_produced_mana():
    engine,reactor,ally,player=board(); tap(engine,ally,player)
    engine.rules.exile(reactor); engine.recompute_continuous_effects()
    assert not mana_abilities_for(ally,engine.state)
    spell=filler(engine,'Artifact spell',type_line='Artifact',mv=1,zone=Zone.HAND)
    engine.cast_spell(player,spell); engine.resolve_until_stable()
    assert spell.zone==Zone.BATTLEFIELD


def test_clone_preserves_restricted_pool_and_spending_rules():
    engine,reactor,ally,player=board(); tap(engine,ally,player)
    clone=GameEngine(engine.state.clone()); copied=clone.state.player_by_id('p1')
    artifact=filler(clone,'Artifact',type_line='Artifact',mv=1,zone=Zone.HAND)
    other=filler(clone,'Creature',power=1,toughness=1,mv=1,zone=Zone.HAND)
    assert clone.can_cast(copied,artifact) and not clone.can_cast(copied,other)


def test_current_artifact_type_of_ability_source_controls_permission():
    from mtg_analyzer.game.effects.core import EffectRegistry
    engine,reactor,ally,player=board(); tap(engine,ally,player)
    source=filler(engine,'Initially plain',power=2,toughness=2,oracle_text='{1}: Draw a card.')
    assert not engine.can_activate(player,source,source.activated_abilities[0])
    effect=EffectRegistry.create('grant_until',{'duration':'end_of_turn','target_kind':'creature',
        'static':{'type':'type_change','params':{'add_types':['artifact']}}})
    effect.apply(engine.rules.context,[source]); engine.recompute_continuous_effects()
    assert engine.can_activate(player,source,source.activated_abilities[0])
    engine.activate_ability(player,source,0); engine.resolve_until_stable()


def test_colorless_mana_cannot_pay_colored_artifact_cost():
    engine,reactor,ally,player=board(); tap(engine,ally,player)
    spell=filler(engine,'White artifact',type_line='Artifact',mv=1,mana_cost_string='{W}',zone=Zone.HAND)
    assert not engine.can_cast(player,spell)


def test_losing_artifact_type_removes_the_mana_grant():
    engine,reactor,ally,player=board()
    ally.card.type_line='Creature'; engine.recompute_continuous_effects()
    assert not mana_abilities_for(ally,engine.state)
    with pytest.raises(ValueError):
        tap(engine,ally,player)

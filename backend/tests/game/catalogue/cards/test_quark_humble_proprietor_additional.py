"""Quark prevents sacrificing Treasure tokens as costs and as instructions."""
import pytest
from mtg_analyzer.game.effects.core import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, RICH
from tests.support.star_trek import advance_to


def board():
    engine=game(players=3,library=20); advance_to(engine,'main1')
    quark=card(engine,'Quark, Humble Proprietor')
    return engine,quark,engine.state.player_by_id('p1')


def treasure(engine,quark,owner='p1'):
    source=quark if owner=='p1' else filler(engine,'Opponent source',player=owner,power=2,toughness=2)
    effect=EffectRegistry.create('create_token',{'token_name':'Treasure','count':1}); effect.source=source
    before={o.instance_id for o in engine.state.battlefield}
    effect.apply(engine.rules.context); engine.recompute_continuous_effects()
    return next(o for o in engine.state.battlefield if o.instance_id not in before)


def test_effect_cannot_sacrifice_a_protected_treasure():
    engine,quark,player=board(); token=treasure(engine,quark)
    engine.rules.sacrifice(player,'artifact',1); engine.resolve_until_stable()
    assert token.zone==Zone.BATTLEFIELD and engine.state.pending_choice is None
    effect=EffectRegistry.create('sacrifice_self',{}); effect.source=token
    effect.apply(engine.rules.context)
    assert token.zone==Zone.BATTLEFIELD


def test_non_token_treasure_is_not_prohibited():
    engine,quark,player=board()
    treasure_card=filler(engine,'Treasure card',type_line='Artifact — Treasure',
        oracle_text='{T}, Sacrifice this artifact: Add one mana of any color.')
    assert not treasure_card.is_token and not treasure_card.cant_be_sacrificed_this_turn
    assert sum(engine.tap_for_mana(player,treasure_card).values())==1


def test_ability_loss_ends_prohibition():
    engine,quark,player=board(); token=treasure(engine,quark)
    aura=card(engine,'Darksteel Mutation'); aura.attached_to=quark.instance_id
    engine.recompute_continuous_effects()
    assert not token.cant_be_sacrificed_this_turn


def test_prohibition_survives_cleanup_and_clone():
    engine,quark,player=board(); token=treasure(engine,quark)
    advance_to(engine,'cleanup'); engine.recompute_continuous_effects()
    assert token.cant_be_sacrificed_this_turn
    clone=GameEngine(engine.state.clone()); clone.recompute_continuous_effects()
    assert clone.state.find_object(token.instance_id).cant_be_sacrificed_this_turn


def test_additional_spell_cost_cannot_sacrifice_treasure():
    engine,quark,player=board(); token=treasure(engine,quark)
    spell=card(engine,'Shrapnel Blast',zone=Zone.HAND); player.mana_pool.add_many(RICH)
    before=player.mana_pool.to_dict()
    with pytest.raises(ValueError):
        engine.cast_spell(player,spell,targets=[engine.state.player_by_id('p2')],sacrifice_choice=token.instance_id)
    assert spell.zone==Zone.HAND and token.zone==Zone.BATTLEFIELD
    assert player.mana_pool.to_dict()==before


def test_prohibition_does_not_prevent_destruction():
    engine,quark,player=board(); token=treasure(engine,quark)
    engine.rules.destroy(token); engine.resolve_until_stable()
    assert token.zone!=Zone.BATTLEFIELD


def test_prohibition_follows_quarks_current_controller():
    engine,quark,player=board()
    own=treasure(engine,quark); other=treasure(engine,quark,'p2')
    quark.controller_id='p2'; engine.recompute_continuous_effects()
    assert not own.cant_be_sacrificed_this_turn and other.cant_be_sacrificed_this_turn
    assert sum(engine.tap_for_mana(player,own).values())==1

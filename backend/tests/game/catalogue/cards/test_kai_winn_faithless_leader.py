"""Kai Winn observes named spells and both stack and immediate mana abilities."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, game, RICH
from tests.support.star_trek import advance_to


def board(name='Sol Ring'):
    engine=game(players=3,library=20); advance_to(engine,'main1')
    kai=card(engine,'Kai Winn, Faithless Leader',zone=Zone.HAND)
    player=engine.state.player_by_id('p1'); player.mana_pool.add_many(RICH)
    engine.cast_spell(player,kai); engine.resolve_until_stable()
    assert engine.state.pending_choice['kind']=='choose_card_name'
    engine.resolve_pending_choice(name)
    return engine,kai


def test_fresh_specs_real_entry_and_name():
    engine,kai=board()
    a,b=specs_for(kai.card),specs_for(kai.card)
    assert a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    assert kai.chosen_card_name=='Sol Ring' and kai.zone==Zone.BATTLEFIELD


@pytest.mark.parametrize('actor,spell_name,loss',[('p2','Sol Ring',3),('p3','Sol Ring',3),
                                               ('p1','Sol Ring',0),('p2','Mind Stone',0)])
def test_only_opponents_casting_chosen_name_lose_life(actor,spell_name,loss):
    engine,kai=board()
    spell=card(engine,spell_name,player=actor,zone=Zone.HAND)
    player=engine.state.player_by_id(actor); player.mana_pool.add_many(RICH)
    before=player.life
    engine.state.active_player_index=int(actor[-1])-1
    engine.cast_spell(player,spell); engine.resolve_until_stable()
    assert player.life==before-loss and spell.zone==Zone.BATTLEFIELD


def test_named_tap_mana_ability_triggers_once_without_using_stack_for_mana():
    engine,kai=board()
    ring=card(engine,'Sol Ring',player='p2'); player=engine.state.player_by_id('p2')
    before=player.life
    assert engine.tap_for_mana(player,ring)=={'C':2}
    assert not engine.state.stack and player.life==before
    engine.resolve_until_stable()
    assert player.life==before-3


def test_named_nonmana_ability_including_sacrifice_cost():
    engine,kai=board('Mind Stone')
    stone=card(engine,'Mind Stone',player='p2'); player=engine.state.player_by_id('p2')
    player.mana_pool.add_many(RICH); before=player.life
    engine.activate_ability(player,stone,0); engine.resolve_until_stable()
    assert stone.zone==Zone.GRAVEYARD and player.life==before-3


def test_own_named_mana_ability_does_not_trigger():
    engine,kai=board()
    ring=card(engine,'Sol Ring'); player=engine.state.player_by_id('p1'); before=player.life
    engine.tap_for_mana(player,ring); engine.resolve_until_stable()
    assert player.life==before


def test_mana_ability_from_hand_is_also_observed():
    engine,kai=board('Elvish Spirit Guide')
    guide=card(engine,'Elvish Spirit Guide',player='p2',zone=Zone.HAND)
    player=engine.state.player_by_id('p2'); before=player.life
    engine.activate_hand_mana_ability(player,guide); engine.resolve_until_stable()
    assert guide.zone==Zone.EXILE and player.life==before-3


def test_trigger_remains_when_named_spell_is_countered_and_kai_leaves():
    engine,kai=board()
    ring=card(engine,'Sol Ring',player='p2',zone=Zone.HAND)
    player=engine.state.player_by_id('p2'); player.mana_pool.add_many(RICH); before=player.life
    engine.state.active_player_index=1
    engine.cast_spell(player,ring)
    engine.rules.put_triggers_on_stack()
    engine.rules.counter_spell(ring); engine.rules.exile(kai); engine.resolve_until_stable()
    assert player.life==before-3 and ring.zone==Zone.GRAVEYARD


def test_clone_preserves_pending_named_mana_trigger():
    engine,kai=board()
    ring=card(engine,'Sol Ring',player='p2'); player=engine.state.player_by_id('p2'); before=player.life
    engine.tap_for_mana(player,ring); engine.rules.put_triggers_on_stack()
    clone=GameEngine(engine.state.clone()); clone.resolve_until_stable()
    assert clone.state.player_by_id('p2').life==before-3 and player.life==before


def test_nonmatching_mana_source_does_not_trigger():
    engine,kai=board('Mind Stone')
    ring=card(engine,'Sol Ring',player='p2'); player=engine.state.player_by_id('p2'); before=player.life
    engine.tap_for_mana(player,ring); engine.resolve_until_stable()
    assert player.life==before


def test_control_change_uses_kai_winns_current_opponents():
    engine,kai=board()
    kai.controller_id='p2'; engine.recompute_continuous_effects()
    ring=card(engine,'Sol Ring'); player=engine.state.player_by_id('p1'); before=player.life
    engine.tap_for_mana(player,ring); engine.resolve_until_stable()
    assert player.life==before-3
    enemy_ring=card(engine,'Sol Ring',player='p2'); other=engine.state.player_by_id('p2'); before=other.life
    engine.tap_for_mana(other,enemy_ring); engine.resolve_until_stable()
    assert other.life==before


def test_land_name_cannot_be_chosen():
    engine,kai=board('Forest')
    assert engine.state.pending_choice['kind']=='choose_card_name'
    assert kai.chosen_card_name!='Forest' and kai.zone!=Zone.BATTLEFIELD
    engine.resolve_pending_choice('Sol Ring')
    assert kai.zone==Zone.BATTLEFIELD and kai.chosen_card_name=='Sol Ring'


def test_sacrificed_copy_matches_the_copied_source_name():
    engine,kai=board('Mind Stone')
    original=card(engine,'Mind Stone',player='p2')
    copied=card(engine,'Phyrexian Metamorph',player='p2')
    from mtg_analyzer.game.effects.core import EffectRegistry
    effect=EffectRegistry.create('become_copy_permanent',{'target_kind':'artifact'})
    effect.source=copied
    effect.apply(engine.rules.context,[original])
    player=engine.state.player_by_id('p2'); player.mana_pool.add_many(RICH); before=player.life
    assert copied.name=='Mind Stone'
    engine.activate_ability(player,copied,0); engine.resolve_until_stable()
    assert copied.zone==Zone.GRAVEYARD
    assert player.life==before-3

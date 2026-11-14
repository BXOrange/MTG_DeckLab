"""The Needs of the Many pays its cost and gives turn-scoped protection."""
import pytest
from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import TargetSpec, legal_targets
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, RICH
from tests.support.star_trek import advance_to


def board():
    engine=game(players=3,library=20); advance_to(engine,'main1')
    spell=card(engine,'The Needs of the Many',zone=Zone.HAND)
    victim=filler(engine,'Sacrifice',power=1,toughness=1)
    ally=filler(engine,'Protected',power=3,toughness=3)
    enemy=filler(engine,'Opponent',player='p2',power=3,toughness=3)
    player=engine.state.player_by_id('p1'); player.mana_pool.add_many(RICH)
    return engine,spell,victim,ally,enemy,player


def cast(engine,spell,victim,player,resolve=True):
    engine.cast_spell(player,spell,sacrifice_choice=victim.instance_id)
    if resolve:
        engine.resolve_until_stable()


def test_fresh_specs_and_additional_cost():
    engine,spell,victim,ally,enemy,player=board()
    a,b=specs_for(spell.card),specs_for(spell.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert a[0].additional_cost=={'sacrifice':'creature'}


def test_cost_is_paid_before_resolution_and_spell_exiles_itself():
    engine,spell,victim,ally,enemy,player=board()
    cast(engine,spell,victim,player,False)
    assert victim.zone==Zone.GRAVEYARD and spell.zone==Zone.STACK
    assert not combat.has(ally,'hexproof')
    engine.resolve_until_stable()
    assert spell.zone==Zone.EXILE
    assert combat.has(ally,'hexproof') and combat.has(ally,'indestructible')
    assert not combat.has(enemy,'hexproof')
    assert continuous.player_has_hexproof(engine.state,'p1')
    assert not continuous.player_has_hexproof(engine.state,'p2')


def test_creature_entering_later_is_not_protected():
    engine,spell,victim,ally,enemy,player=board(); cast(engine,spell,victim,player)
    late=filler(engine,'Later',power=3,toughness=3)
    assert not combat.has(late,'hexproof') and not combat.has(late,'indestructible')


def test_opponent_cannot_target_player_but_own_source_can():
    engine,spell,victim,ally,enemy,player=board(); cast(engine,spell,victim,player)
    spec=TargetSpec(kind='player')
    assert 'p1' not in {o.get('player_id') for o in legal_targets(engine.state,'p2',spec,source=enemy)}
    assert 'p1' in {o.get('player_id') for o in legal_targets(engine.state,'p1',spec,source=ally)}


@pytest.mark.parametrize('combat_damage',[False,True])
def test_prevents_combat_and_noncombat_damage_but_not_life_loss(combat_damage):
    engine,spell,victim,ally,enemy,player=board(); cast(engine,spell,victim,player)
    before=player.life
    engine.rules.deal_damage(player,7,source=enemy,combat=combat_damage)
    assert player.life==before
    engine.rules.lose_life(player,2)
    assert player.life==before-2


def test_indestructible_prevents_destruction():
    engine,spell,victim,ally,enemy,player=board(); cast(engine,spell,victim,player)
    engine.rules.destroy(ally); engine.resolve_until_stable()
    assert ally.zone==Zone.BATTLEFIELD


def test_cleanup_removes_all_turn_scoped_shields():
    engine,spell,victim,ally,enemy,player=board(); cast(engine,spell,victim,player)
    advance_to(engine,'cleanup'); engine.recompute_continuous_effects()
    assert not continuous.player_has_hexproof(engine.state,'p1')
    assert not combat.has(ally,'hexproof') and not combat.has(ally,'indestructible')
    before=player.life; engine.rules.deal_damage(player,3,source=enemy)
    assert player.life==before-3


def test_countered_spell_keeps_sacrifice_and_gives_no_shields():
    engine,spell,victim,ally,enemy,player=board(); cast(engine,spell,victim,player,False)
    engine.rules.counter_spell(spell); engine.resolve_until_stable()
    assert spell.zone==Zone.GRAVEYARD and victim.zone==Zone.GRAVEYARD
    assert not continuous.player_has_hexproof(engine.state,'p1')
    assert not combat.has(ally,'hexproof')


def test_cannot_sacrifice_opponents_creature():
    engine,spell,victim,ally,enemy,player=board()
    with pytest.raises(ValueError):
        cast(engine,spell,enemy,player)
    assert spell.zone==Zone.HAND and enemy.zone==Zone.BATTLEFIELD


def test_clone_preserves_player_shield_after_spell_exiles():
    engine,spell,victim,ally,enemy,player=board(); cast(engine,spell,victim,player)
    clone=GameEngine(engine.state.clone()); clone.recompute_continuous_effects()
    assert continuous.player_has_hexproof(clone.state,'p1')
    copied=clone.state.player_by_id('p1'); before=copied.life
    clone.rules.deal_damage(copied,4,source=clone.state.find_object(enemy.instance_id))
    assert copied.life==before and clone.state.find_object(spell.instance_id).zone==Zone.EXILE


def test_player_spell_target_becomes_illegal_when_shield_resolves_first():
    engine,spell,victim,ally,enemy,player=board()
    bolt=card(engine,'Lightning Bolt',player='p2',zone=Zone.HAND)
    opponent=engine.state.player_by_id('p2'); opponent.mana_pool.add_many(RICH)
    engine.cast_spell(opponent,bolt,targets=[player])
    before=player.life
    cast(engine,spell,victim,player)
    assert player.life==before and bolt.zone==Zone.GRAVEYARD
    assert spell.zone==Zone.EXILE


def test_blink_removes_creature_shields_but_keeps_player_shield():
    engine,spell,victim,ally,enemy,player=board(); cast(engine,spell,victim,player)
    engine.rules.exile(ally); engine.rules.return_from_graveyard(ally,'battlefield')
    engine.recompute_continuous_effects()
    assert not combat.has(ally,'hexproof') and not combat.has(ally,'indestructible')
    assert continuous.player_has_hexproof(engine.state,'p1')


def test_existing_static_hexproof_remains_after_marker_expires():
    engine,spell,victim,ally,enemy,player=board()
    card(engine,'Shalai, Voice of Plenty')
    cast(engine,spell,victim,player)
    advance_to(engine,'cleanup'); engine.recompute_continuous_effects()
    assert continuous.player_has_hexproof(engine.state,'p1')
    assert not any(getattr(e,'player_hexproof',False) for e in player.player_effects)

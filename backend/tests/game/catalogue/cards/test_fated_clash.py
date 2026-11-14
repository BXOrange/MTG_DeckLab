"""Fated Clash's independent combat condition and two-target board wipe."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, RICH
from tests.support.star_trek import advance_to


def _board():
    engine=game(players=3,library=30)
    advance_to(engine,'main1')
    spell=card(engine,'Fated Clash',zone=Zone.HAND)
    own=filler(engine,'Own',power=2,toughness=4)
    other=filler(engine,'Other',player='p2',power=2,toughness=4)
    extra=filler(engine,'Extra',player='p3',power=2,toughness=4)
    engine.state.player_by_id('p1').mana_pool.add_many(RICH)
    return engine,spell,own,other,extra


def _cast(engine,spell,own,other):
    engine.cast_spell(engine.state.player_by_id('p1'),spell,targets=[own,other])


def test_fresh_specs_binding_and_conditional_flash():
    engine,spell,own,other,extra=_board()
    a,b=specs_for(spell.card),specs_for(spell.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert spell.conditional_flash is not None and len(spell.spell_effects)==3


@pytest.mark.parametrize('attacking,blocking,allowed',[(False,False,False),(True,False,False),(False,True,False),(True,True,True)])
def test_off_turn_timing_requires_both_an_attacker_and_a_blocker(attacking,blocking,allowed):
    engine,spell,own,other,extra=_board()
    engine.state.active_player_index=1
    engine.state.current_step='declare_blockers'
    own.attacking=attacking
    other.blocking=own.instance_id if blocking else None
    assert engine.can_cast(engine.state.player_by_id('p1'),spell,targets=[own,other])==allowed


def test_normal_sorcery_window_does_not_require_combat():
    engine,spell,own,other,extra=_board()
    assert engine.can_cast(engine.state.player_by_id('p1'),spell,targets=[own,other])
    _cast(engine,spell,own,other)
    engine.resolve_until_stable()
    assert own.zone==other.zone==Zone.BATTLEFIELD and extra.zone==Zone.GRAVEYARD
    assert combat.has(own,'indestructible') and combat.has(other,'indestructible')
    advance_to(engine,'cleanup')
    assert not combat.has(own,'indestructible') and not combat.has(other,'indestructible')


def test_real_combat_allows_cast_and_preserves_noncombatant_targets():
    engine,spell,own,other,extra=_board()
    attacker=filler(engine,'Attacker',power=1,toughness=4)
    blocker=filler(engine,'Blocker',player='p2',power=1,toughness=4)
    advance_to(engine,'declare_attackers')
    engine.declare_attackers(engine.state.player_by_id('p1'),[{'attacker':attacker,'defender':engine.state.player_by_id('p2')}])
    advance_to(engine,'declare_blockers')
    engine.declare_blockers(engine.state.player_by_id('p2'),[(blocker,attacker)])
    engine.state.player_by_id('p1').mana_pool.add_many(RICH)
    assert engine.can_cast(engine.state.player_by_id('p1'),spell,targets=[own,other])
    _cast(engine,spell,own,other)
    engine.resolve_until_stable()
    assert own.zone==other.zone==Zone.BATTLEFIELD
    assert attacker.zone==blocker.zone==extra.zone==Zone.GRAVEYARD


@pytest.mark.parametrize('which',['own','opponent','both'])
def test_illegal_targets_skip_their_grants_and_all_illegal_fizzles(which):
    engine,spell,own,other,extra=_board()
    _cast(engine,spell,own,other)
    if which in {'own','both'}:
        engine.rules.exile(own)
    if which in {'opponent','both'}:
        engine.rules.exile(other)
    engine.resolve_until_stable()
    assert extra.zone==(Zone.BATTLEFIELD if which=='both' else Zone.GRAVEYARD)
    survivor=other if which=='own' else own
    if which!='both':
        assert survivor.zone==Zone.BATTLEFIELD and combat.has(survivor,'indestructible')


def test_losing_timing_condition_after_cast_does_not_stop_resolution():
    engine,spell,own,other,extra=_board()
    own.attacking=True
    other.blocking=own.instance_id
    engine.state.active_player_index=1
    _cast(engine,spell,own,other)
    own.attacking=False
    other.blocking=None
    engine.resolve_until_stable()
    assert extra.zone==Zone.GRAVEYARD and own.zone==other.zone==Zone.BATTLEFIELD


def test_clone_preserves_two_target_groups():
    engine,spell,own,other,extra=_board()
    _cast(engine,spell,own,other)
    clone=GameEngine(engine.state.clone())
    clone.resolve_until_stable()
    assert clone.state.find_object(own.instance_id).zone==Zone.BATTLEFIELD
    assert clone.state.find_object(other.instance_id).zone==Zone.BATTLEFIELD
    assert clone.state.find_object(extra.instance_id).zone==Zone.GRAVEYARD
    assert extra.zone==Zone.BATTLEFIELD


def test_own_target_changing_control_becomes_illegal_but_wipe_still_happens():
    engine,spell,own,other,extra=_board()
    _cast(engine,spell,own,other)
    own.controller_id='p3'
    engine.resolve_until_stable()
    assert own.zone==extra.zone==Zone.GRAVEYARD
    assert other.zone==Zone.BATTLEFIELD and combat.has(other,'indestructible')


def test_phased_out_attacker_cannot_satisfy_flash_condition():
    engine,spell,own,other,extra=_board()
    own.attacking=True
    own.phased_out=True
    other.blocking=own.instance_id
    engine.state.active_player_index=1
    assert not engine.can_cast(engine.state.player_by_id('p1'),spell)

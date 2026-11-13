"""Human Torch: payment, exact source visit, and repeating damage triggers."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, cast
from tests.support.star_trek import advance_to


def _board():
    engine = game(players=4)
    source = card(engine, 'Human Torch')
    return engine, source, engine.state.player_by_id('p1')


def _attack(engine, source, pool=True, pay=True):
    advance_to(engine, 'declare_attackers')
    player = engine.state.player_by_id(source.controller_id)
    if pool:
        player.mana_pool.add_many({'R': 1, 'G': 1, 'W': 1, 'U': 1})
    engine.declare_attackers(player, [{'attacker': source, 'defender': engine.state.player_by_id('p2')}])
    engine.resolve_until_stable()
    if engine.state.pending_choice:
        assert engine.state.pending_choice['kind'] == 'pay_cost_then'
        engine.resolve_pending_choice('pay' if pay else 'decline')
        engine.resolve_until_stable()


def _damage(engine, source, player='p2', amount=2, combat_damage=True):
    engine.rules.deal_damage(engine.state.player_by_id(player), amount, source=source, combat=combat_damage)
    engine.resolve_until_stable()


def _life(engine):
    return [p.life for p in engine.state.players]


def test_specs_fresh_and_bound():
    engine, source, _ = _board()
    a, b = specs_for(source.card), specs_for(source.card)
    assert len(a) == 2 and a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    engine, source, _ = _board()
    assert len(source.triggered_abilities) == 2


@pytest.mark.parametrize('cast_noncreature,active,expected', [(True,0,True),(False,0,False),(True,1,False)])
def test_beginning_of_own_combat_intervening_condition(cast_noncreature, active, expected):
    engine, source, _ = _board()
    advance_to(engine, 'main1')
    if cast_noncreature:
        cast(engine, filler(engine, 'Setup spell', type_line='Instant', zone=Zone.HAND))
    engine.state.active_player_index = active
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='begin_combat'))
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert all(combat.has(source, k) == expected for k in ('flying', 'double_strike', 'haste'))


@pytest.mark.parametrize('pool,pay', [(False,True),(True,False)])
def test_unpaid_attack_does_not_create_trigger(pool,pay):
    engine, source, _ = _board()
    _attack(engine, source, pool=pool, pay=pay)
    assert not engine.state.turn_scoped_triggers
    _damage(engine, source)
    assert _life(engine) == [20,18,20,20]


def test_paid_attack_consumes_all_four_colors_and_repeats():
    engine, source, player = _board()
    _attack(engine, source)
    assert len(engine.state.turn_scoped_triggers) == 1
    assert player.mana_pool.total() == 0
    _damage(engine, source, amount=3)
    assert _life(engine) == [20,17,17,17]
    _damage(engine, source, player='p3', amount=2)
    assert _life(engine) == [20,15,15,15]


@pytest.mark.parametrize('kind', ['noncombat','other_source','self','creature'])
def test_only_this_source_combat_damage_to_opponent_triggers(kind):
    engine, source, _ = _board()
    _attack(engine, source)
    if kind == 'creature':
        target = filler(engine, 'Blocker', player='p2', power=1, toughness=6)
        engine.rules.deal_damage(target, 2, source=source, combat=True)
        engine.resolve_until_stable()
    else:
        dealer = filler(engine, 'Other', power=2, toughness=2) if kind == 'other_source' else source
        _damage(engine, dealer, player='p1' if kind == 'self' else 'p2', combat_damage=kind!='noncombat')
    assert engine.state.player_by_id('p3').life == 20
    assert engine.state.player_by_id('p4').life == 20


def test_clone_keeps_delayed_trigger():
    engine, source, _ = _board()
    _attack(engine, source)
    clone = GameEngine(engine.state.clone())
    _damage(clone, clone.state.find_object(source.instance_id))
    assert _life(clone) == [20,18,18,18]
    assert _life(engine) == [20,20,20,20]


def test_leaving_and_returning_does_not_inherit_old_trigger():
    engine, source, _ = _board()
    _attack(engine, source)
    engine.rules.exile(source)
    engine.rules.return_from_graveyard(source, "battlefield")
    _damage(engine, source)
    assert _life(engine) == [20,18,20,20]


def test_already_triggered_damage_survives_source_departure():
    engine, source, _ = _board()
    _attack(engine, source)
    engine.rules.deal_damage(engine.state.player_by_id('p2'), 2, source=source, combat=True)
    engine.rules.put_triggers_on_stack()
    engine.rules.exile(source)
    engine.resolve_until_stable()
    assert _life(engine) == [20,18,18,18]


def test_real_noncreature_cast_grants_keywords_and_double_strike_repeats_damage():
    engine, source, _ = _board()
    advance_to(engine, 'main1')
    spell = filler(engine, 'A spark', type_line='Instant', zone=Zone.HAND)
    cast(engine, spell)
    _attack(engine, source)
    assert all(combat.has(source,k) for k in ('flying','double_strike','haste'))
    advance_to(engine, 'combat_damage')
    engine.resolve_until_stable()
    assert _life(engine) == [20,14,14,14]


def test_delayed_trigger_and_keywords_expire():
    engine, source, _ = _board()
    advance_to(engine, 'main1')
    cast(engine, filler(engine, 'Setup spell', type_line='Instant', zone=Zone.HAND))
    _attack(engine, source)
    assert combat.has(source, 'double_strike')
    engine._step_cleanup()
    engine.state.internal_turn.number += 1
    _damage(engine, source)
    assert _life(engine) == [20,18,20,20]
    assert not engine.state.turn_scoped_triggers
    assert not any(combat.has(source,k) for k in ('flying','double_strike','haste'))


def test_delayed_controller_stays_fixed_after_source_is_stolen():
    engine, source, _ = _board()
    _attack(engine, source)
    source.controller_id = 'p3'
    _damage(engine, source)
    assert _life(engine) == [20,18,18,18]


def test_pending_payment_survives_clone():
    engine, source, player = _board()
    advance_to(engine,'declare_attackers')
    player.mana_pool.add_many({'R':1,'G':1,'W':1,'U':1})
    engine.declare_attackers(player,[{'attacker':source,'defender':engine.state.player_by_id('p2')}])
    engine.resolve_until_stable()
    assert engine.state.pending_choice['kind'] == 'pay_cost_then'
    clone = GameEngine(engine.state.clone())
    clone.resolve_pending_choice('pay')
    _damage(clone,clone.state.find_object(source.instance_id))
    assert _life(clone) == [20,18,18,18]
    assert not engine.state.turn_scoped_triggers

"""Gavel's combat trigger, all-counter bonuses and both Equip payments."""

import pytest

from mtg_analyzer.api.cards import coverage_for
from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.events import EventType, GameEvent
from tests.support.catalogue import battlefield_object, two_player_game


ORACLE = (
    "At the beginning of combat on your turn, put a charge counter on this Equipment.\n"
    "Equipped creature gets +1/+1 for each counter on this Equipment.\n"
    "As long as this Equipment has four or more counters on it, equipped creature has double strike.\n"
    "Equip—Pay {3} or remove a counter from this Equipment."
)


def _board():
    engine, player = two_player_game()
    engine.begin_turn()
    engine.state.current_step = "main1"
    gavel = battlefield_object(engine, player.id, "Gavel of the Righteous", "Artifact — Equipment",
                               oracle_text=ORACLE, keywords=["Equip"])
    bind_from_catalogue(gavel)
    host = battlefield_object(engine, player.id, "Bear", "Creature — Bear",
                              is_creature=True, power=2, toughness=2)
    return engine, player, gavel, host


def test_complete_fresh_specs_bind_without_a_free_equip_option():
    _, _, gavel, _ = _board()
    assert coverage_for(gavel.card)["modeled"]
    first, second = specs_for(gavel.card), specs_for(gavel.card)
    assert all(a is not b for a, b in zip(first, second))
    assert len(gavel.triggered_abilities) == 1
    assert len(gavel.static_effects) == 2
    assert len(gavel.activated_abilities) == 2


@pytest.mark.parametrize("step,controller,expected", [
    ("begin_combat", "p1", 1), ("begin_combat", "p2", 0), ("upkeep", "p1", 0),
])
def test_charge_counter_only_at_own_combat(step, controller, expected):
    engine, _, gavel, _ = _board()
    engine.state.active_player_index = 0 if controller == "p1" else 1
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step=step, player_id=controller,
                                      controller_id=controller))
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert gavel.counters.get("charge", 0) == expected


@pytest.mark.parametrize("remove_counter", [False, True])
def test_both_payments_attach_and_update_all_counter_bonuses(remove_counter):
    engine, player, gavel, host = _board()
    gavel.counters.update({"charge": 3, "shield": 1})
    player.mana_pool.add_many({"C": 3})
    index = next(i for i, a in enumerate(gavel.activated_abilities)
                 if bool(a.cost.remove_counters) == remove_counter)
    engine.activate_ability(player, gavel, index, targets=[host])
    assert sum(gavel.counters.values()) == (3 if remove_counter else 4)
    engine.resolve_until_stable()
    assert gavel.attached_to == host.instance_id
    assert (host.power, host.toughness) == ((5, 5) if remove_counter else (6, 6))
    assert combat.has(host, "double_strike") == (not remove_counter)
    assert player.mana_pool.total() == (3 if remove_counter else 0)


def test_removing_a_noncharge_counter_can_pay_and_remove_double_strike():
    engine, player, gavel, host = _board()
    gavel.attached_to = host.instance_id
    gavel.counters["shield"] = 4
    engine.recompute_continuous_effects()
    assert combat.has(host, "double_strike")
    index = next(i for i, a in enumerate(gavel.activated_abilities) if a.cost.remove_counters)
    engine.activate_ability(player, gavel, index, targets=[host])
    engine.resolve_until_stable()
    assert gavel.counters["shield"] == 3
    assert host.power == 5
    assert not combat.has(host, "double_strike")


def test_payment_target_and_sorcery_restrictions():
    engine, player, gavel, host = _board()
    assert all(not engine.can_activate(player, gavel, a) for a in gavel.activated_abilities)
    gavel.counters["charge"] = 1
    player.mana_pool.add_many({"C": 3})
    enemy = battlefield_object(engine, "p2", "Enemy", "Creature", is_creature=True, power=2, toughness=2)
    for index, ability in enumerate(gavel.activated_abilities):
        assert engine.can_activate(player, gavel, ability)
        with pytest.raises(ValueError):
            engine.activate_ability(player, gavel, index, targets=[enemy])
    assert gavel.counters["charge"] == 1
    assert player.mana_pool.total() == 3
    engine.state.current_step = "begin_combat"
    assert all(not engine.can_activate(player, gavel, a) for a in gavel.activated_abilities)

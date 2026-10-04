"""MEC-109 — RULE 702.152 Blitz, costs, grants and zone identity."""
from __future__ import annotations

import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import MODELED, parse_oracle
from mtg_analyzer.services.game_session import GameSession


def game():
    engine = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    for player in engine.state.players:
        player.life = 20
    engine.begin_turn()
    engine.state.current_step = "main1"
    return engine, engine.state, engine.state.active_player


def card(name="Blitzer", cost="{1}{R}", body="", mana="{4}{R}", keywords=None):
    return Card(id=name, name=name, type_line="Creature — Warrior", is_creature=True,
                mana_cost_string=mana, converted_mana_cost=5, power=3, toughness=3,
                keywords=keywords or ["Blitz"], oracle_text=f"{body}\nBlitz {cost}".strip())


def add(player, printed, zone=Zone.HAND):
    obj = GameObject(printed, owner_id=player.id, zone=zone)
    player.zones[zone].append(obj)
    bind_from_catalogue(obj)
    return obj


def seed_library(player):
    for i in range(4):
        add(player, Card(id=f"draw{i}", name=f"Draw {i}", type_line="Land", is_land=True), Zone.LIBRARY)


def end_step(engine):
    engine._fire_delayed_triggers("end")
    engine.resolve_until_stable()


def henzie(player, state):
    printed = card('Henzie "Toolbox" Torre', body=(
        "Each creature spell you cast with mana value 4 or greater has blitz. "
        "The blitz cost is equal to its mana cost.\n"
        "Blitz costs you pay cost {1} less for each time you've cast your commander from the command zone this game."
    ), keywords=[], cost="{B}{R}{G}")
    # Henzie has no printed blitz; only the spells it grants it to do.
    printed.oracle_text = printed.oracle_text.rsplit("\nBlitz", 1)[0]
    printed.keywords = []
    obj = GameObject(printed, owner_id=player.id, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def test_blitz_offer_and_session_payment_die_and_draw():
    engine, state, player = game()
    seed_library(player)
    obj = add(player, card())
    player.mana_pool.add_many({"R": 2})
    assert not engine.can_cast(player, obj)
    offer = next(a for a in engine.legal_actions(player) if a.get("blitz") == 0)
    assert offer["blitz_cost_label"]
    GameSession(engine).apply_action(offer)
    engine.resolve_until_stable()
    assert obj.blitz_cost_paid and combat.has(obj, "haste")
    assert player.mana_pool.total() == 0
    engine._fire_delayed_triggers("end")
    assert obj in state.battlefield  # respondable delayed ability
    engine.resolve_until_stable()
    assert obj in player.graveyard and len(player.hand) == 1
    assert not obj.blitz_cost_paid and not state.delayed_triggers


def test_normal_cast_does_not_gain_blitz_consequences():
    engine, state, player = game()
    obj = add(player, card())
    player.mana_pool.add_many({"R": 5})
    engine.cast_spell(player, obj)
    engine.resolve_until_stable()
    assert not combat.has(obj, "haste")
    assert not state.delayed_triggers
    end_step(engine)
    assert obj in state.battlefield


def test_combat_death_draws_only_once():
    engine, state, player = game()
    seed_library(player)
    obj = add(player, card())
    player.mana_pool.add_many({"R": 2})
    engine.cast_spell(player, obj, blitz=0)
    engine.resolve_until_stable()
    engine.rules.deal_damage(obj, 3)
    engine.resolve_until_stable()
    assert obj in player.graveyard and len(player.hand) == 1
    end_step(engine)
    assert len(player.hand) == 1


@pytest.mark.parametrize("action", ["exile", "return_to_hand"])
def test_non_death_departure_no_draw_and_returned_object_not_sacrificed(action):
    engine, state, player = game()
    seed_library(player)
    obj = add(player, card())
    player.mana_pool.add_many({"R": 2})
    engine.cast_spell(player, obj, blitz=0)
    engine.resolve_until_stable()
    getattr(engine.rules, action)(obj)
    player.zones[obj.zone].remove(obj)
    state.add_to_battlefield(obj)
    engine.recompute_continuous_effects()
    assert not combat.has(obj, "haste")
    end_step(engine)
    assert obj in state.battlefield and len(player.hand) == 0


def test_control_change_changes_draw_controller_but_caster_cannot_sacrifice_it():
    engine, state, player = game()
    other = state.player_by_id("p2")
    seed_library(player)
    seed_library(other)
    obj = add(player, card())
    player.mana_pool.add_many({"R": 2})
    engine.cast_spell(player, obj, blitz=0)
    engine.resolve_until_stable()
    obj.controller_id = other.id
    engine.recompute_continuous_effects()
    end_step(engine)
    assert obj in state.battlefield
    engine.rules.destroy(obj)
    engine.resolve_until_stable()
    assert len(other.hand) == 1 and len(player.hand) == 0


@pytest.mark.parametrize("name,cost,life,discard", [
    ("Tenacious Underdog", "{2}{B}{B}, Pay 2 life", 2, 0),
    ("Sabin, Master Monk", "{2}{R}{R}, Discard a card", 0, 1),
])
def test_graveyard_blitz_restricted_permission_and_full_cost(name, cost, life, discard):
    engine, state, player = game()
    seed_library(player)
    obj = add(player, card(name, cost, body="You may cast this card from your graveyard using its blitz ability."), Zone.GRAVEYARD)
    fodder = add(player, Card(id="fodder", name="Fodder", type_line="Land", is_land=True))
    player.mana_pool.add_many({"B": 4, "R": 4})
    assert parse_oracle(obj.card).coverage == MODELED
    assert not engine.can_cast(player, obj)
    assert engine.can_cast(player, obj, blitz=0)
    action = next(a for a in engine.legal_actions(player) if a.get("blitz") == 0)
    if discard:
        assert action["discard_cost"]["count"] == 1
        action["discard_choices"] = [fodder.instance_id]
    GameSession(engine).apply_action(action)
    engine.resolve_until_stable()
    assert player.life == 20-life
    if discard:
        assert fodder in player.graveyard
    end_step(engine)
    assert obj in player.graveyard and obj not in player.exile


def test_blitz_discard_cannot_pay_with_the_spell_itself():
    engine, state, player = game()
    obj = add(player, card(cost="{R}, Discard a card"))
    player.mana_pool.add_many({"R": 5})
    assert not engine.can_cast(player, obj, blitz=0)
    assert engine.can_cast(player, obj)


def test_blitz_life_cost_cannot_be_paid_without_life():
    engine, state, player = game()
    obj = add(player, card(cost="{R}, Pay 2 life"))
    player.life = 1
    player.mana_pool.add_many({"R": 5})
    assert not engine.can_cast(player, obj, blitz=0)


@pytest.mark.parametrize("invalid", [-1, 1, True, "0"])
def test_invalid_instance_and_conflicting_alternative_costs_rejected(invalid):
    engine, state, player = game()
    obj = add(player, card())
    player.mana_pool.add_many({"R": 8})
    assert not engine.can_cast(player, obj, blitz=invalid)
    assert not engine.can_cast(player, obj, blitz=0, evoke=True)


def test_henzie_grants_and_reduces_both_printed_and_granted_instances():
    engine, state, player = game()
    grant = henzie(player, state)
    assert parse_oracle(grant.card).coverage == MODELED
    player.commander_casts[grant.instance_id] = 2
    obj = add(player, card(cost="{3}{R}"))
    assert engine.effective_cast_cost(player, obj, blitz=0).raw == "{1}{R}"
    assert engine.effective_cast_cost(player, obj, blitz=1).raw == "{2}{R}"
    assert engine.effective_cast_cost(player, obj).raw == "{4}{R}"
    player.mana_pool.add_many({"R": 3})
    offers = [a for a in engine.legal_actions(player) if a.get("blitz") is not None]
    assert [a["blitz"] for a in offers] == [0, 1]
    engine.cast_spell(player, obj, blitz=1)
    engine.resolve_until_stable()
    assert len(state.delayed_triggers) == 1 and len(obj.granted_triggered_abilities) == 1


def test_henzie_grants_to_unkeyworded_creature_and_stops_when_leaving():
    engine, state, player = game()
    grant = henzie(player, state)
    plain = Card(id="plain", name="Plain", type_line="Creature", is_creature=True,
                 mana_cost_string="{3}{G}", converted_mana_cost=4, power=4, toughness=4)
    obj = add(player, plain)
    player.mana_pool.add_many({"G": 5})
    assert engine.can_cast(player, obj, blitz=0)
    engine.rules.exile(grant)
    assert not engine.can_cast(player, obj, blitz=0)


def test_henzie_grant_mana_value_threshold():
    engine, state, player = game()
    henzie(player, state)
    obj = add(player, Card(id="small", name="Small", is_creature=True, type_line="Creature",
                          mana_cost_string="{1}{G}", converted_mana_cost=2, power=2, toughness=2))
    player.mana_pool.add_many({"G": 5})
    assert not engine.can_cast(player, obj, blitz=0)


def test_blitz_haste_survives_cleanup_and_next_end_step_is_any_players():
    engine, state, player = game()
    seed_library(player)
    obj = add(player, card())
    player.mana_pool.add_many({"R": 2})
    # It enters after the beginning of an end step, so it waits for the next.
    engine._fire_delayed_triggers("end")
    engine.cast_spell(player, obj, blitz=0)
    engine.resolve_until_stable()
    engine._step_cleanup()
    engine.recompute_continuous_effects()
    assert combat.has(obj, "haste") and obj in state.battlefield
    state.active_player_index = 1
    end_step(engine)
    assert obj in player.graveyard and len(player.hand) == 1


def test_blitz_spell_copy_inherits_payment_and_arms_own_delayed_trigger():
    engine, state, player = game()
    seed_library(player)
    obj = add(player, card())
    player.mana_pool.add_many({"R": 2})
    engine.cast_spell(player, obj, blitz=0)
    copy = engine.rules.copy_spell(obj, player.id)[0].obj
    engine.resolve_until_stable()
    assert copy in state.battlefield and combat.has(copy, "haste")
    assert len(state.delayed_triggers) == 2
    end_step(engine)
    assert len(player.hand) == 2


def test_two_blitz_casts_of_same_card_do_not_duplicate_dies_grant():
    engine, state, player = game()
    seed_library(player)
    obj = add(player, card("Tenacious Underdog", "{R}", body="You may cast this card from your graveyard using its blitz ability."))
    player.mana_pool.add_many({"R": 2})
    engine.cast_spell(player, obj, blitz=0)
    engine.resolve_until_stable()
    engine.rules.destroy(obj)
    engine.resolve_until_stable()
    engine.cast_spell(player, obj, blitz=0)
    engine.resolve_until_stable()
    assert len(obj.granted_triggered_abilities) == 1
    end_step(engine)
    assert obj in player.graveyard and len(player.hand) == 2


def test_countered_blitz_spell_has_no_battlefield_consequences():
    engine, state, player = game()
    obj = add(player, card())
    player.mana_pool.add_many({"R": 2})
    engine.cast_spell(player, obj, blitz=0)
    engine.rules.counter_spell(obj)
    assert not obj.blitz_cost_paid and not state.delayed_triggers
    engine.rules.return_from_graveyard(obj)
    engine.recompute_continuous_effects()
    assert not combat.has(obj, "haste")


def test_henzie_blitz_total_includes_commander_tax_and_optional_kicker():
    engine, state, player = game()
    grant = henzie(player, state)
    player.commander_casts[grant.instance_id] = 2
    obj = add(player, card(cost="{3}{R}", body="Kicker {2}", keywords=["Blitz", "Kicker"]), Zone.COMMAND)
    obj.is_commander = True
    player.commander_casts[obj.instance_id] = 1
    # {3}{R} + {2} tax + {2} kicker - {3} Henzie reduction.
    assert engine.effective_cast_cost(player, obj, blitz=0, kicked=1).converted_mana_cost == 5


def test_perpetual_blitz_choice_filters_hand_and_survives_zone_changes():
    engine, state, player = game()
    seed_library(player)
    for name in ["First", "Second"]:
        add(player, Card(id=name, name=name, type_line="Creature", is_creature=True,
                        mana_cost_string="{R}", converted_mana_cost=1, power=2, toughness=2))
    already = add(player, card())
    source = add(player, card("Riveteers Provocateur", "{B}{R}", keywords=["Blitz", "Menace"], body=(
        "Menace\nWhen this creature enters, choose a creature card in your hand without blitz. "
        "It perpetually gains blitz. The blitz cost is equal to its mana cost."
    )))
    player.mana_pool.add_many({"R": 8, "B": 1})
    engine.cast_spell(player, source, blitz=0)
    engine.resolve_until_stable()
    choice = state.pending_choice
    assert choice["kind"] == "choose_objects"
    options = {int(option["id"]) for option in choice["options"]}
    assert already.instance_id not in options
    chosen = player.hand[0]
    engine.rules.resolve_choice(str(chosen.instance_id))
    engine.resolve_until_stable()
    assert "blitz" in chosen.perpetual_keywords
    engine.cast_spell(player, chosen, blitz=0)
    engine.resolve_until_stable()
    engine.rules.return_to_hand(chosen)
    assert "blitz" in chosen.perpetual_keywords and engine.can_cast(player, chosen, blitz=0)
    engine.cast_spell(player, chosen, blitz=0)
    engine.resolve_until_stable()
    end_step(engine)
    assert chosen in player.graveyard


@pytest.mark.full_cache
@pytest.mark.parametrize("name", [
    'Henzie "Toolbox" Torre', 'Riveteers Provocateur', 'Tenacious Underdog',
    'Sabin, Master Monk', 'Night Clubber', 'Workshop Warchief', 'Riveteers Requisitioner',
])
def test_real_cache_blitz_cards_bind_complete_text(name):
    from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

    printed = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    assert printed is not None
    assert parse_oracle(printed).coverage == MODELED
    engine, state, player = game()
    obj = add(player, printed)
    if name == 'Henzie "Toolbox" Torre':
        assert {a.layer for a in obj.static_effects} >= {"grant_blitz", "blitz_cost_reduction"}
    else:
        assert obj.parametric_keywords["blitz"]["cost"]


def test_blitz_can_auto_tap_lands_for_alternative_cost():
    engine, state, player = game()
    obj = add(player, card())
    for i in range(2):
        land = GameObject(Card(id=f"mountain{i}", name="Mountain", type_line="Basic Land — Mountain", is_land=True),
                          owner_id=player.id, zone=Zone.BATTLEFIELD)
        state.add_to_battlefield(land)
    assert not engine.can_cast(player, obj, blitz=0)
    action = next(a for a in engine.legal_actions(player) if a.get("blitz") == 0)
    GameSession(engine).apply_action(action)
    assert obj.zone == Zone.STACK and obj.blitz_cost_paid
    assert all(o.tapped for o in state.battlefield if o.is_land)


def test_removing_all_abilities_suppresses_draw_but_not_delayed_sacrifice():
    from mtg_analyzer.game.effects.core import StaticAbility

    engine, state, player = game()
    seed_library(player)
    obj = add(player, card())
    player.mana_pool.add_many({"R": 2})
    engine.cast_spell(player, obj, blitz=0)
    engine.resolve_until_stable()
    source = GameObject(Card(id="strip", name="Strip", type_line="Enchantment"),
                        owner_id=player.id, zone=Zone.BATTLEFIELD)
    source.static_effects.append(StaticAbility("ability", affects="all_creatures",
                                             params={"lose_all_abilities": True}, source=source))
    state.add_to_battlefield(source)
    engine.recompute_continuous_effects()
    assert not combat.has(obj, "haste")
    end_step(engine)
    assert obj in player.graveyard and len(player.hand) == 0


def test_henzie_leaving_after_cast_does_not_remove_blitz_consequences():
    engine, state, player = game()
    seed_library(player)
    source = henzie(player, state)
    plain = Card(id="plain", name="Plain", type_line="Creature", is_creature=True,
                 mana_cost_string="{3}{R}", converted_mana_cost=4, power=4, toughness=4)
    obj = add(player, plain)
    player.mana_pool.add_many({"R": 4})
    engine.cast_spell(player, obj, blitz=0)
    engine.rules.exile(source)
    engine.resolve_until_stable()
    assert combat.has(obj, "haste")
    end_step(engine)
    assert obj in player.graveyard and len(player.hand) == 1


def test_henzie_uses_announced_x_for_creature_spell_mana_value():
    engine, state, player = game()
    henzie(player, state)
    obj = add(player, Card(id="hydra", name="Hydra", type_line="Creature — Hydra", is_creature=True,
                          mana_cost_string="{X}{G}", converted_mana_cost=1, power=1, toughness=1))
    player.mana_pool.add_many({"G": 6})
    assert not engine.can_cast(player, obj, x=2, blitz=0)
    assert engine.can_cast(player, obj, x=3, blitz=0)
    offer = next(a for a in engine.legal_actions(player) if a.get("blitz") == 0)
    assert offer["min_x"] == 3 and offer["max_x"] == 5
    GameSession(engine).apply_action({**offer, "x": 4})
    engine.resolve_until_stable()
    assert obj.blitz_cost_paid and obj.x_paid == 4 and player.mana_pool.total() == 1

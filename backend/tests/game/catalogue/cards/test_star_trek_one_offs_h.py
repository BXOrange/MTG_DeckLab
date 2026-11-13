"""Linked hand/graveyard exile on All Good Things... and S.S. Botany Bay.

Fixtures transcribe the complete Scryfall records, so these tests run offline
even when the local bulk cache predates the Star Trek release.
"""
import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.linked_exile import linked_cards
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.star_trek import attack, cast, stock_library, vanilla


def _card(name):
    if name == "All Good Things...":
        return Card(id="all-good-things", name=name, type_line="Enchantment — Saga",
                    mana_cost_string="{3}{G}{U}", converted_mana_cost=5,
                    oracle_text="(As this Saga enters and after your draw step, add a lore counter. Sacrifice after IV.)\n"
                    "I, II, III — Draw two cards, then exile a card from your hand.\n"
                    "IV — If all cards exiled with this Saga share a card type, you gain 10 life.")
    assert name == "S.S. Botany Bay"
    return Card(id="botany-bay", name=name, type_line="Legendary Artifact — Spacecraft",
                mana_cost_string="{3}", converted_mana_cost=3, vehicle_power=3, vehicle_toughness=5,
                keywords=["Station"], is_legendary=True,
                oracle_text="{T}: Each opponent exiles a card from their graveyard. You may exile a card from your graveyard.\n"
                "Station\n8+ | Flying\n"
                "Whenever S.S. Botany Bay deals combat damage to a player, return each creature card you own exiled with it to the battlefield.")


def _game(name=None, players=2, via_steps=False):
    engine = GameEngine.new_game([(f"p{i}", f"Player {i}", [_card(name)] if i == 1 and name else [])
                                 for i in range(1, players + 1)], starting_hand=1 if name else 0, starting_life=20)
    for player in engine.state.players:
        for obj in player.hand:
            bind_from_catalogue(obj)
    if via_steps:
        from tests.support.star_trek import advance_to
        for player in engine.state.players:
            stock_library(engine, player.id, 5)
        engine.start()
        advance_to(engine, "main1")
    else:
        engine.begin_turn()
        engine.state.current_step = "main1"
    return engine, engine.state.player_by_id("p1"), engine.state.player_by_id("p2")


def _object(engine, player_id, name, type_line, zone):
    obj = GameObject(Card(id=name, name=name, type_line=type_line,
                          is_creature="Creature" in type_line, is_land="Land" in type_line,
                          power=2 if "Creature" in type_line else None,
                          toughness=2 if "Creature" in type_line else None), owner_id=player_id, zone=zone)
    engine.state.player_by_id(player_id).add_to_zone(obj, zone)
    return obj


def _board(engine, name):
    obj = GameObject(_card(name), owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    bind_from_catalogue(obj)
    obj.summoning_sick = False
    engine.state.add_to_battlefield(obj)
    engine.recompute_continuous_effects()
    return obj


def _answer(engine, obj_or_decline):
    answer = str(obj_or_decline.instance_id) if hasattr(obj_or_decline, "instance_id") else obj_or_decline
    choice = engine.state.pending_choice
    assert choice and any(str(o["id"]) == answer for o in choice["options"]), choice
    engine.resolve_pending_choice(answer)
    engine.resolve_until_stable()


@pytest.mark.parametrize("name", ["All Good Things...", "S.S. Botany Bay"])
def test_specs_fresh_valid_and_bound(name):
    first, second = specs_for(_card(name)), specs_for(_card(name))
    assert first and first[0] is not second[0] and first[0].effects[0] is not second[0].effects[0]
    for spec in first:
        spec.validate()
    engine, _, _ = _game()
    obj = _board(engine, name)
    assert obj.triggered_abilities
    if name == "S.S. Botany Bay":
        assert len(obj.activated_abilities) == 2  # tap ability plus Station


def _saga(types):
    engine, p1, _ = _game("All Good Things...")
    selected = []
    for index, type_line in reversed(list(enumerate(types))):
        _object(engine, "p1", f"Padding {index}", "Land", Zone.LIBRARY)
        selected.insert(0, _object(engine, "p1", f"Pick {index}", type_line, Zone.LIBRARY))
    saga = p1.hand[0]
    cast(engine, p1, saga)
    for chapter, picked in enumerate(selected, 1):
        if chapter > 1:
            engine.rules.advance_sagas(p1)
            engine.resolve_until_stable()
        _answer(engine, picked)
        assert picked in p1.exile and picked in linked_cards(engine.state, saga)
    return engine, p1, saga, selected


@pytest.mark.parametrize("types,life", [
    (["Artifact Creature — Borg"] * 3, 30),
    (["Artifact Creature — Borg", "Enchantment Creature — Human", "Artifact Enchantment"], 20),
    (["Legendary Artifact", "Legendary Creature — Human", "Legendary Land"], 20),
    (["Kindred Instant — Wizard", "Kindred Sorcery — Wizard", "Kindred Enchantment — Wizard"], 30),
])
def test_all_good_things_draws_exiles_then_checks_one_common_card_type(types, life):
    engine, p1, saga, selected = _saga(types)
    assert len(p1.hand) == 3 and saga.counters["lore"] == 3
    engine.rules.advance_sagas(p1)
    engine.resolve_until_stable()
    assert p1.life == life
    assert saga in p1.graveyard  # final chapter finishes before Saga sacrifice


@pytest.mark.parametrize("remaining", [0, 1])
def test_all_good_things_empty_or_single_current_linked_card_still_gains_life(remaining):
    engine, p1, saga, selected = _saga(["Artifact", "Creature", "Land"])
    for obj in selected[remaining:]:
        engine.rules.return_to_hand(obj)
        # An unrelated new exile visit is not linked to the Saga.
        engine.rules.exile(obj)
    assert len(linked_cards(engine.state, saga)) == remaining
    engine.rules.advance_sagas(p1)
    engine.resolve_until_stable()
    assert p1.life == 30


def test_all_good_things_final_chapter_reads_original_source_visit_after_source_leaves():
    engine, p1, saga, _ = _saga(["Artifact", "Creature", "Land"])
    engine.rules.advance_sagas(p1)
    engine.rules.return_to_hand(saga)
    engine.resolve_until_stable()
    assert saga in p1.hand and p1.life == 20


def test_botany_multiplayer_choosers_and_own_optional_graveyard_exile_survive_clone():
    engine, p1, p2 = _game(players=3)
    ship = _board(engine, "S.S. Botany Bay")
    p2_cards = [_object(engine, "p2", f"P2 {i}", "Creature", Zone.GRAVEYARD) for i in range(2)]
    p3_card = _object(engine, "p3", "P3", "Land", Zone.GRAVEYARD)
    own_card = _object(engine, "p1", "Mine", "Creature", Zone.GRAVEYARD)
    engine.activate_ability(p1, ship, ability_index=0)
    engine.resolve_until_stable()
    assert ship.tapped and engine.state.pending_choice["player_id"] == "p2"
    engine = GameEngine(engine.state.clone())
    _answer(engine, p2_cards[1])
    assert engine.state.pending_choice["player_id"] == "p1"
    _answer(engine, own_card)
    ship = engine.state.find_object(ship.instance_id)
    assert {o.instance_id for o in linked_cards(engine.state, ship)} == {
        p2_cards[1].instance_id, p3_card.instance_id, own_card.instance_id,
    }
    assert engine.state.find_object(p2_cards[0].instance_id).zone == Zone.GRAVEYARD


def test_botany_optional_exile_can_be_declined():
    engine, p1, _ = _game()
    ship = _board(engine, "S.S. Botany Bay")
    own_card = _object(engine, "p1", "Mine", "Creature", Zone.GRAVEYARD)
    engine.activate_ability(p1, ship, ability_index=0)
    engine.resolve_until_stable()
    _answer(engine, "decline")
    assert own_card in p1.graveyard and not linked_cards(engine.state, ship)


def test_botany_resolving_tap_ability_keeps_old_source_link_after_ship_leaves():
    engine, p1, p2 = _game()
    ship = _board(engine, "S.S. Botany Bay")
    old_incarnation = ship.zone_incarnation
    mine = _object(engine, "p1", "Mine", "Creature", Zone.GRAVEYARD)
    engine.activate_ability(p1, ship, ability_index=0)
    engine.rules.return_to_hand(ship)
    engine.resolve_until_stable()
    _answer(engine, mine)
    assert mine in linked_cards(engine.state, ship, old_incarnation)
    cast(engine, p1, ship)
    assert not linked_cards(engine.state, ship)
    assert mine in p1.exile


def test_botany_other_sources_and_noncombat_damage_do_not_return_cards():
    engine, p1, p2 = _game()
    ship = _board(engine, "S.S. Botany Bay")
    mine = _object(engine, "p1", "Mine", "Creature", Zone.GRAVEYARD)
    engine.activate_ability(p1, ship, ability_index=0)
    engine.resolve_until_stable()
    _answer(engine, mine)
    engine.rules.deal_damage(p2, 1, source=ship, combat=False)
    engine.resolve_until_stable()
    assert mine in p1.exile
    bear = vanilla(engine, "p1")
    engine.rules.deal_damage(p2, 1, source=bear, combat=True)
    engine.resolve_until_stable()
    assert mine in p1.exile


def test_botany_station_levels_and_combat_return_only_owned_creatures():
    engine, p1, p2 = _game(via_steps=True)
    ship = _board(engine, "S.S. Botany Bay")
    donor = vanilla(engine, "p1", "Donor", 1, 1)
    ship.counters["charge"] = 7
    engine.recompute_continuous_effects()
    assert not ship.is_creature and not combat.has(ship, "flying")
    engine.activate_ability(p1, ship, ability_index=1, targets=[donor])
    engine.resolve_until_stable()
    assert donor.tapped and ship.counters.get("charge") == 8
    assert ship.is_creature and (ship.power, ship.toughness) == (3, 5) and combat.has(ship, "flying")
    mine = _object(engine, "p1", "Mine", "Creature", Zone.GRAVEYARD)
    theirs = _object(engine, "p2", "Theirs", "Creature", Zone.GRAVEYARD)
    land = _object(engine, "p1", "Land", "Land", Zone.GRAVEYARD)
    # First tap ability links one card from each graveyard.
    engine.activate_ability(p1, ship, ability_index=0)
    engine.resolve_until_stable()
    _answer(engine, land)
    ship.tapped = False
    engine.activate_ability(p1, ship, ability_index=0)
    engine.resolve_until_stable()
    _answer(engine, mine)
    ship.tapped = False
    attack(engine, p1, ship)
    assert p2.life == 17 and mine.zone == Zone.BATTLEFIELD
    assert theirs in p2.exile and land in p1.exile
    assert {o.instance_id for o in linked_cards(engine.state, ship)} == {theirs.instance_id, land.instance_id}

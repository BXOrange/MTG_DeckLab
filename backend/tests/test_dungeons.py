"""Dungeons (RULE 309), the venture keyword action (RULE 701.49) and the
initiative's own venture triggers (RULE 726.2).

Reference: CR 309, 701.49, 726.2. The narrative lives in
`docs/implementation-state/Done_Backend.md` ("Dungeons").
"""

import pytest

from mtg_analyzer.game import dungeons
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.services.dungeon_database import default_dungeon_database


def make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def library(eng, count=10, player_id="p1"):
    player = eng.state.player_by_id(player_id)
    for i in range(count):
        card = Card(id=f"c{i}", name=f"Card {i}", type_line="Creature — Bear",
                    is_creature=True, power=2, toughness=2)
        player.add_to_zone(GameObject(card, owner_id=player_id, zone=Zone.LIBRARY), Zone.LIBRARY)
    return player


# -- The catalogue and the room graph ---------------------------------------


def test_the_catalogue_holds_the_four_real_dungeons():
    names = {entry["name"] for entry in default_dungeon_database().all_dungeons()}
    assert names == {
        "Tomb of Annihilation",
        "Lost Mine of Phandelver",
        "Dungeon of the Mad Mage",
        "Undercity",
    }


def test_room_lines_parse_into_a_directed_graph():
    dungeon = dungeons.dungeon_by_name("Lost Mine of Phandelver")
    assert dungeon.top_room.name == "Cave Entrance"
    assert dungeon.top_room.leads_to == ["Goblin Lair", "Mine Tunnels"]
    # RULE 309.5b: exactly one bottommost room per dungeon.
    assert [r.name for r in dungeon.rooms if r.is_last] == ["Temple of Dumathoin"]


def test_undercity_is_kept_out_of_the_free_choice():
    """RULE 309.2a vs. 701.49d: Undercity's own text gates it behind
    "venture into Undercity"."""
    assert dungeons.dungeon_by_name("Undercity").restricted is True
    assert "Undercity" not in {d.name for d in dungeons.choosable_dungeons()}


def test_each_dungeon_instance_is_fresh():
    """A `Dungeon` carries a player's venture marker, so two players must
    never share one."""
    a, b = dungeons.dungeon_by_name("Undercity"), dungeons.dungeon_by_name("Undercity")
    a.current_room = "Forge"
    assert b.current_room is None


def test_a_room_effect_binds_through_the_ordinary_effect_grammar():
    dungeon = dungeons.dungeon_by_name("Dungeon of the Mad Mage")
    specs = dungeons.room_effect_specs(dungeon.room("Yawning Portal"))
    assert [s["type"] for s in specs] == ["gain_life"]


def test_an_unmodeled_room_effect_fails_closed():
    """A room whose text the parser doesn't model keeps its place in the
    graph but resolves with no effect — never a guessed one. PAR-13
    (2026-08-04) closed 8 of the then-9 unmodeled rooms (including this
    test's original example, Twisted Caverns); Throne of the Dead Three is
    the one genuine remaining gap — see test_par13_dungeons_and_variants.py
    for why (a "reveal top N, choose one, place with counters, shuffle the
    rest back" shape no other cached card needs)."""
    dungeon = dungeons.dungeon_by_name("Undercity")
    assert dungeons.room_effect_specs(dungeon.room("Throne of the Dead Three")) == []


# -- Venturing (RULE 701.49) -------------------------------------------------


def test_first_venture_enters_a_chosen_dungeon_at_its_top_room():
    eng = make_engine()
    player = library(eng)
    eng.rules.venture_into_the_dungeon(player)
    choice = eng.state.pending_choice
    assert choice["kind"] == "choose_dungeon"
    eng.rules.resolve_choose_dungeon_choice("Lost Mine of Phandelver")
    assert player.dungeon.name == "Lost Mine of Phandelver"
    assert player.dungeon.current_room == "Cave Entrance"


def test_entering_a_room_triggers_its_room_ability():
    """RULE 309.4c: "When you move your venture marker into this room, …"."""
    eng = make_engine()
    player = library(eng)
    eng.rules.venture_into_the_dungeon(player, "Dungeon of the Mad Mage")
    # Yawning Portal — "You gain 1 life."
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    assert player.life == 21


def test_venture_named_dungeon_skips_the_choice():
    eng = make_engine()
    player = library(eng)
    eng.rules.venture_into_the_dungeon(player, dungeons.UNDERCITY)
    assert eng.state.pending_choice is None
    assert player.dungeon.name == "Undercity"
    assert player.dungeon.current_room == "Secret Entrance"


def test_a_second_venture_advances_and_asks_when_two_arrows_lead_out():
    eng = make_engine()
    player = library(eng)
    eng.rules.venture_into_the_dungeon(player, "Undercity")
    eng.rules.venture_into_the_dungeon(player)
    choice = eng.state.pending_choice
    assert choice["kind"] == "venture_room"
    assert {o["id"] for o in choice["options"]} == {"Forge", "Lost Well"}
    eng.rules.resolve_venture_room_choice("Lost Well")
    assert player.dungeon.current_room == "Lost Well"


def test_a_single_arrow_advances_without_asking():
    eng = make_engine()
    player = library(eng)
    eng.rules.venture_into_the_dungeon(player, "Undercity")
    eng.rules.resolve_venture_room_choice  # noqa: B018 - documented below
    eng.rules.venture_into_the_dungeon(player)
    eng.rules.resolve_venture_room_choice("Lost Well")
    eng.rules.venture_into_the_dungeon(player)   # Lost Well → Arena / Stash
    eng.rules.resolve_venture_room_choice("Stash")
    eng.rules.venture_into_the_dungeon(player)   # Stash → Catacombs (single arrow)
    assert eng.state.pending_choice is None
    assert player.dungeon.current_room == "Catacombs"


def test_a_named_venture_is_ignored_once_you_are_already_in_a_dungeon():
    """RULE 701.49d: the name only picks a *new* dungeon."""
    eng = make_engine()
    player = library(eng)
    eng.rules.venture_into_the_dungeon(player, "Dungeon of the Mad Mage")
    eng.rules.venture_into_the_dungeon(player, dungeons.UNDERCITY)
    assert player.dungeon.name == "Dungeon of the Mad Mage"
    assert player.dungeon.current_room == "Dungeon Level"


# -- Completion (RULE 309.6 / 309.7) -----------------------------------------


def _walk_to_last_room(eng, player, name="Lost Mine of Phandelver"):
    eng.rules.venture_into_the_dungeon(player, name)
    while not player.dungeon.on_last_room:
        eng.rules.venture_into_the_dungeon(player)
        if eng.state.pending_choice:
            eng.rules.resolve_venture_room_choice(eng.state.pending_choice["options"][0]["id"])


def test_completing_a_dungeon_removes_it_from_the_game():
    eng = make_engine()
    player = library(eng, count=30)
    seen = []
    eng.state.subscribe(lambda e: seen.append(e))
    _walk_to_last_room(eng, player)
    assert player.dungeon.current_room == "Temple of Dumathoin"
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    assert player.dungeon is None
    assert player.completed_dungeons == ["Lost Mine of Phandelver"]
    assert [e.type for e in seen].count(EventType.DUNGEON_COMPLETED) == 1


def test_venturing_after_completion_starts_a_new_dungeon():
    eng = make_engine()
    player = library(eng, count=30)
    _walk_to_last_room(eng, player)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    eng.rules.venture_into_the_dungeon(player, "Tomb of Annihilation")
    assert player.dungeon.name == "Tomb of Annihilation"
    assert player.dungeon.current_room == "Trapped Entry"


def test_venturing_from_the_bottommost_room_completes_then_re_enters():
    """RULE 701.49c: the ability may not have resolved (a countered trigger,
    or a venture from another source in response) — venturing from the last
    room still completes that dungeon and starts a fresh one."""
    eng = make_engine()
    player = library(eng, count=30)
    _walk_to_last_room(eng, player)
    eng.rules.pending_triggers.clear()
    eng.rules.venture_into_the_dungeon(player, "Tomb of Annihilation")
    assert player.completed_dungeons == ["Lost Mine of Phandelver"]
    assert player.dungeon.name == "Tomb of Annihilation"


# -- The initiative (RULE 726.2) --------------------------------------------


def test_taking_the_initiative_ventures_into_undercity():
    eng = make_engine()
    player = library(eng)
    eng.rules.take_initiative(player)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    assert player.dungeon.name == "Undercity"


def test_retaking_the_initiative_ventures_again():
    """RULE 726.5: no second designation, but the trigger still fires."""
    eng = make_engine()
    player = library(eng)
    eng.rules.take_initiative(player)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    eng.rules.take_initiative(player)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    if eng.state.pending_choice:
        eng.rules.resolve_venture_room_choice(eng.state.pending_choice["options"][0]["id"])
    assert eng.state.initiative_id == player.id
    assert player.dungeon.current_room != "Secret Entrance"


def test_the_initiative_holders_upkeep_ventures():
    eng = make_engine()
    player = library(eng)
    eng.state.initiative_id = "p1"
    eng.state.active_player_index = 0
    eng.rules.pending_triggers.clear()
    eng.state.fire_event(
        __import__("mtg_analyzer.models.events", fromlist=["GameEvent"]).GameEvent(
            EventType.STEP_BEGIN, step="upkeep"
        )
    )
    descriptions = [ability.description for ability, _ in eng.rules.pending_triggers]
    assert any("ventures into Undercity" in d for d in descriptions)


# -- Parser recognition ------------------------------------------------------


def test_parser_recognizes_venture_into_the_dungeon():
    from mtg_analyzer.parser.oracle.gate import parse_oracle

    card = Card(
        id="v", name="Venturer", type_line="Creature — Human",
        is_creature=True, power=2, toughness=2,
        oracle_text="When this creature enters, venture into the dungeon.",
    )
    result = parse_oracle(card)
    assert result.coverage == "MODELED"
    effects = [e for spec in result.specs for e in spec.effects]
    assert [(e.type, e.params.get("dungeon")) for e in effects] == [("venture", None)]


def test_parser_recognizes_the_named_venture_variant():
    from mtg_analyzer.parser.oracle.gate import parse_oracle

    card = Card(
        id="u", name="Undercity Diver", type_line="Creature — Human",
        is_creature=True, power=2, toughness=2,
        oracle_text="When this creature enters, venture into Undercity.",
    )
    result = parse_oracle(card)
    assert result.coverage == "MODELED"
    effects = [e for spec in result.specs for e in spec.effects]
    assert [(e.type, e.params.get("dungeon")) for e in effects] == [("venture", "undercity")]


def test_a_ventured_room_ability_actually_resolves_end_to_end():
    """A real card: "When this creature enters, venture into the dungeon."
    → the chosen dungeon's first room ability resolves."""
    eng = make_engine()
    player = library(eng, count=20)
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    card = Card(
        id="v", name="Venturer", type_line="Creature — Human",
        is_creature=True, power=2, toughness=2,
        oracle_text="When this creature enters, venture into the dungeon.",
    )
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    from mtg_analyzer.models.events import GameEvent

    eng.state.fire_event(
        GameEvent(
            EventType.ENTERS_BATTLEFIELD,
            controller_id="p1",
            instance_id=obj.instance_id,
            object=obj.name,
            object_types=sorted(obj.type_words),
        )
    )
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    eng.resolve_pending_choice("Dungeon of the Mad Mage")
    assert player.dungeon.name == "Dungeon of the Mad Mage"
    assert player.life == 21  # Yawning Portal — "You gain 1 life."

"""MEC-140: RULE 701.72 Assimilate on a real engine, with the real cached cards.

From the battlefield (701.72a) and from a graveyard, exile and library (701.72b); the Borg type replaces the creature
types but keeps "Artifact" and every non-creature subtype; the linked "assimilated with this Saga" return (701.72c);
a permanent that left and returned is no longer assimilated (RULE 400.7).
"""
from __future__ import annotations

import pytest

from mtg_analyzer.game.assimilate import assimilate, assimilated_with
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.card_cache import get_cached_card
from tests.support.star_trek import advance_to, cast, game, on_battlefield, stock_library, vanilla

CARDS = [
    "Assimilate the Wounded", "Assimilation Assessor", "Borg Cube", "Borg Queen, Perfection Manifest",
    "Death Is Irrelevant", "Gift of Perfection", "The Best of Both Worlds", "The Borg Queen",
]


def creature_card(name="Elf Druid", type_line="Creature — Elf Druid", power=1, toughness=1):
    return Card(id=name.replace(" ", ""), name=name, type_line=type_line, is_creature=True,
                power=power, toughness=toughness)


def put(engine, player_id, card, zone):
    """Place ``card`` in ``zone`` of ``player_id`` (graveyard/exile/library/battlefield) and return the object."""
    obj = GameObject(card, owner_id=player_id, zone=zone)
    player = engine.state.player_by_id(player_id)
    if zone == Zone.BATTLEFIELD:
        obj.controller_id, obj.summoning_sick = player_id, False
        engine.state.add_to_battlefield(obj)
    else:
        player.add_to_zone(obj, zone)
    return obj


def settle(eng, *prefer):
    """Resolve the stack, answering each trigger-target prompt with the first preferred pick it offers."""
    for _ in range(6):
        eng.resolve_until_stable()
        choice = eng.state.pending_choice
        if not choice:
            return
        offered = {str(o["id"]): o["id"] for o in choice["options"]}
        pick = next((p for p in prefer if str(p) in offered), next(iter(offered.values())))
        eng.resolve_pending_choice(pick)
    raise AssertionError(f"choice never settled: {eng.state.pending_choice}")


def is_borg_artifact_creature(obj):
    return ("artifact" in obj.type_words and "creature" in obj.type_words and obj.has_subtype("borg"))


@pytest.mark.parametrize("name", CARDS)
def test_real_cards_are_modeled(name):
    card = get_cached_card(name)
    assert card is not None and parse_oracle(card).modeled


@pytest.mark.parametrize("text", [
    "assimilate target creature card from your graveyard",  # a graveyard scope this action never prints
    "assimilate a land card exiled with ~",
    "assimilate up to 2 creature cards exiled with ~",
    "assimilate target creature card from an opponent's graveyard tapped",
])
def test_adversarial_variants_stay_unclaimed(text):
    assert parse_effect_body(text + ".") is None


def test_parse_shapes():
    battlefield = match_clause("assimilate target nonartifact creature an opponent controls")
    assert [s.type for s in battlefield] == ["assimilate"]
    assert battlefield[0].params["creature_filter"] == {"without_card_type": "artifact"}
    wounded = match_clause(
        "for each opponent, assimilate up to 1 target creature card from that player's graveyard that was put "
        "there from the battlefield this turn")
    assert wounded[0].params == {
        "target_kind": "that_player_graveyard_creature", "optional": True, "per_player": "opponents",
        "creature_filter": {"died_this_turn": True}}


def test_battlefield_assimilation_takes_control_adds_counter_and_borg_type():
    """RULE 701.72a on a Legendary Enchantment Creature: the Borg type replaces Elf Druid, the rest stays."""
    eng, p1, p2 = game("Gift of Perfection")
    card = creature_card("Odd Druid", "Legendary Enchantment Creature — Elf Druid", 2, 2)
    target = put(eng, "p2", card, Zone.BATTLEFIELD)
    source = put(eng, "p1", creature_card("Borg Source", "Creature — Borg"), Zone.BATTLEFIELD)
    assert assimilate(eng.rules, "p1", target, source) is target
    eng.recompute_continuous_effects()
    assert target.controller_id == "p1" and target.owner_id == "p2"
    assert target.counters.get("+1/+1") == 1 and (target.power, target.toughness) == (3, 3)
    assert is_borg_artifact_creature(target)
    assert not target.has_subtype("elf") and not target.has_subtype("druid")  # RULE 205.3m: creature types replaced
    assert "enchantment" in target.type_words and "legendary" in target.type_words  # types and supertypes are kept
    assert assimilated_with(eng.state, source) == [target]


def test_noncreature_subtype_is_kept_and_type_change_outlasts_the_source():
    """RULE 205.3m: only creature types are replaced, so a Vehicle stays a Vehicle; RULE 611.2a: no duration."""
    eng, p1, p2 = game("Gift of Perfection")
    ride = put(eng, "p2", Card(id="Ride", name="Ride", type_line="Artifact — Vehicle", vehicle_power=3, vehicle_toughness=3),
               Zone.BATTLEFIELD)
    source = put(eng, "p1", creature_card("Borg Source", "Creature — Borg"), Zone.BATTLEFIELD)
    assimilate(eng.rules, "p1", ride, source)
    eng.recompute_continuous_effects()
    assert is_borg_artifact_creature(ride) and ride.has_subtype("vehicle")
    eng.rules.exile(source)  # the assimilating object leaves; the effect and the control change do not
    eng.recompute_continuous_effects()
    assert is_borg_artifact_creature(ride) and ride.controller_id == "p1"


@pytest.mark.parametrize("zone", [Zone.GRAVEYARD, Zone.EXILE, Zone.LIBRARY])
def test_assimilating_a_card_from_another_zone_enters_as_a_borg_with_a_counter(zone):
    """RULE 701.72b from a graveyard, exile and the library: under the taker's control with the counter on entry."""
    eng, p1, p2 = game("Gift of Perfection")
    card = put(eng, "p2", creature_card("Dead Elf", "Creature — Elf Warrior", 2, 2), zone)
    source = put(eng, "p1", creature_card("Borg Source", "Creature — Borg"), Zone.BATTLEFIELD)
    assert assimilate(eng.rules, "p1", card, source) is card
    eng.recompute_continuous_effects()
    assert card.zone == Zone.BATTLEFIELD and card.controller_id == "p1" and card.owner_id == "p2"
    assert card.counters.get("+1/+1") == 1 and (card.power, card.toughness) == (3, 3)
    assert is_borg_artifact_creature(card) and not card.has_subtype("elf")
    assert assimilated_with(eng.state, source) == [card]


def test_instants_cannot_be_assimilated_from_a_graveyard():
    eng, p1, p2 = game("Gift of Perfection")
    spell = put(eng, "p2", Card(id="Zap", name="Zap", type_line="Instant", is_instant=True), Zone.GRAVEYARD)
    assert assimilate(eng.rules, "p1", spell, None) is None and spell.zone == Zone.GRAVEYARD


def test_leaving_and_returning_is_a_new_object_and_no_longer_assimilated():
    """RULE 400.7 / 701.72c: the Borg type, the counter and the link all belong to the one battlefield visit."""
    eng, p1, p2 = game("Gift of Perfection")
    target = put(eng, "p2", creature_card(), Zone.BATTLEFIELD)
    source = put(eng, "p1", creature_card("Borg Source", "Creature — Borg"), Zone.BATTLEFIELD)
    assimilate(eng.rules, "p1", target, source)
    eng.rules.blink(target)
    eng.recompute_continuous_effects()
    assert target.zone == Zone.BATTLEFIELD and target.controller_id == "p2"
    assert not is_borg_artifact_creature(target) and target.has_subtype("elf")
    assert "+1/+1" not in target.counters or target.counters["+1/+1"] == 0
    assert assimilated_with(eng.state, source) == []


def test_best_of_both_worlds_steals_a_nonartifact_creature_then_chapter_three_returns_it():
    eng, p1, p2 = game("The Best of Both Worlds")
    victim = vanilla(eng, "p2", "Elf Druid")
    artifact_creature = put(eng, "p2", creature_card("Gear", "Artifact Creature — Construct"), Zone.BATTLEFIELD)
    saga = next(o for o in p1.hand)
    cast(eng, p1, saga)
    settle(eng, victim.instance_id)
    assert victim.controller_id == "p1" and victim.counters.get("+1/+1") == 1
    assert is_borg_artifact_creature(victim) and (victim.power, victim.toughness) == (3, 3)  # the 2/2 plus the counter
    assert artifact_creature.controller_id == "p2"  # "nonartifact" excludes the artifact creature
    saga = next(o for o in eng.state.battlefield if o.name == "The Best of Both Worlds")
    eng.rules.advance_sagas(p1)  # chapter II
    eng.resolve_until_stable()
    assert (victim.power, victim.toughness) == (5, 5)  # artifact creatures you control get +2/+2 until end of turn
    eng.rules.advance_sagas(p1)  # chapter III
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    # RULE 701.72c: the Borg assimilated with this Saga returns under its owner's control, as a new object.
    assert victim.zone == Zone.BATTLEFIELD and victim.controller_id == "p2"
    assert not is_borg_artifact_creature(victim) and not victim.counters.get("+1/+1")


def test_assimilate_the_wounded_takes_only_a_creature_that_died_this_turn():
    eng, p1, p2 = game("Assimilate the Wounded")
    dead = vanilla(eng, "p2", "Fresh Corpse", 3, 3)
    eng.rules.destroy(dead)
    old = put(eng, "p2", creature_card("Old Corpse", "Creature — Zombie", 5, 5), Zone.GRAVEYARD)
    assert dead.zone == Zone.GRAVEYARD
    spell = next(o for o in p1.hand)
    cast(eng, p1, spell, targets=[dead])
    assert dead.zone == Zone.BATTLEFIELD and dead.controller_id == "p1" and is_borg_artifact_creature(dead)
    assert old.zone == Zone.GRAVEYARD  # it did not die this turn: not a legal target


def test_borg_queen_perfection_manifest_reanimates_from_an_opponents_graveyard():
    eng, p1, p2 = game("Borg Queen, Perfection Manifest")
    dead = put(eng, "p2", creature_card("Dead Elf", "Creature — Elf", 2, 2), Zone.GRAVEYARD)
    cast(eng, p1, next(o for o in p1.hand))
    settle(eng, dead.instance_id)
    assert dead.zone == Zone.BATTLEFIELD and dead.controller_id == "p1"
    assert is_borg_artifact_creature(dead) and dead.counters.get("+1/+1") == 1
    assert (dead.power, dead.toughness) == (5, 3)  # 2/2 + counter + the Queen's +2/+0 for artifact creatures


def test_death_is_irrelevant_assimilates_at_the_end_step():
    eng, p1, p2 = game("Death Is Irrelevant", via_steps=True)
    dead = put(eng, "p2", creature_card("Dead Elf", "Creature — Elf", 2, 2), Zone.GRAVEYARD)
    cast(eng, p1, next(o for o in p1.hand))
    advance_to(eng, "end")
    settle(eng, dead.instance_id)
    assert dead.zone == Zone.BATTLEFIELD and dead.controller_id == "p1" and is_borg_artifact_creature(dead)


def test_assimilation_assessor_assimilates_a_creature_exiled_with_it():
    eng, p1, p2 = game("Assimilation Assessor", via_steps=True)
    exiled_target = put(eng, "p2", creature_card("Dead Elf", "Creature — Elf", 2, 2), Zone.GRAVEYARD)
    land_card = put(eng, "p2", Card(id="Isle", name="Isle", type_line="Basic Land — Island", is_land=True), Zone.GRAVEYARD)
    cast(eng, p1, next(o for o in p1.hand))
    settle(eng, "p2")
    assessor = next(o for o in eng.state.battlefield if o.name == "Assimilation Assessor")
    assert exiled_target.zone == Zone.EXILE and land_card.zone == Zone.EXILE  # the whole graveyard, linked to it
    assessor.summoning_sick = False
    from tests.support.star_trek import attack
    attack(eng, p1, assessor)
    settle(eng)
    assert exiled_target.zone == Zone.BATTLEFIELD and exiled_target.controller_id == "p1"
    assert is_borg_artifact_creature(exiled_target) and land_card.zone == Zone.EXILE  # "a creature card" only


def test_borg_cube_assimilates_a_linked_card_else_exiles_a_creature():
    eng, p1, p2 = game("Borg Cube")
    victim = vanilla(eng, "p2", "Elf Druid")
    cast(eng, p1, next(o for o in p1.hand))
    settle(eng, victim.instance_id)
    cube = next(o for o in eng.state.battlefield if o.name == "Borg Cube")
    # Nothing is exiled with it yet, so "if you can't" exiles the creature, which is then exiled with the Cube.
    assert victim.zone == Zone.EXILE
    from mtg_analyzer.game.linked_exile import linked_cards
    assert linked_cards(eng.state, cube) == [victim]


def test_the_borg_queen_exiles_until_a_creature_assimilates_it_and_bottoms_the_rest():
    eng, p1, p2 = game("The Borg Queen")
    stock_library(eng, "p2", 2)  # the top of the library is the end of the list
    hit = put(eng, "p2", creature_card("Library Elf", "Creature — Elf", 2, 2), Zone.LIBRARY)
    p2.library.remove(hit)
    p2.library.insert(1, hit)  # one filler above it, one below
    above = p2.library[-1]
    cast(eng, p1, next(o for o in p1.hand))
    settle(eng, "p2")
    assert hit.zone == Zone.BATTLEFIELD and hit.controller_id == "p1" and is_borg_artifact_creature(hit)
    assert above.zone == Zone.LIBRARY and p2.library[0] is above  # exiled, then put on the bottom of the library


def test_gift_of_perfection_reveals_until_a_creature_and_bottoms_the_rest():
    eng, p1, p2 = game("Gift of Perfection")
    stock_library(eng, "p2", 2)
    hit = put(eng, "p2", creature_card("Library Elf", "Creature — Elf", 2, 2), Zone.LIBRARY)
    p2.library.remove(hit)
    p2.library.insert(1, hit)
    above = p2.library[-1]
    cast(eng, p1, next(o for o in p1.hand))
    assert hit.zone == Zone.BATTLEFIELD and hit.controller_id == "p1" and is_borg_artifact_creature(hit)
    assert above.zone == Zone.LIBRARY and p2.library[0] is above  # RULE 701.20: the rest goes to the bottom


def test_gift_of_perfection_with_two_opponents_lets_you_pick_and_bottoms_the_other_in_its_owners_library():
    """RULE 701.72b: one of the revealed creature cards; the other goes to the bottom of *its owner's* library."""
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    from mtg_analyzer.game.game_engine import GameEngine
    cards = [get_cached_card("Gift of Perfection")]
    eng = GameEngine.new_game([("p1", "A", cards), ("p2", "B", []), ("p3", "C", [])], starting_hand=1, starting_life=20)
    for obj in eng.state.player_by_id("p1").hand:
        bind_from_catalogue(obj)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1, p2, p3 = (eng.state.player_by_id(pid) for pid in ("p1", "p2", "p3"))
    hits = {}
    for pid in ("p2", "p3"):
        stock_library(eng, pid, 1)
        hits[pid] = put(eng, pid, creature_card(f"Elf {pid}", "Creature — Elf", 2, 2), Zone.LIBRARY)
        lib = eng.state.player_by_id(pid).library
        lib.remove(hits[pid])
        lib.append(hits[pid])  # the creature is the top card
    cast(eng, p1, next(o for o in p1.hand))
    assert eng.state.pending_choice and eng.state.pending_choice["kind"] == "choose_objects"
    eng.resolve_pending_choice(hits["p3"].instance_id)
    eng.resolve_until_stable()
    assert hits["p3"].zone == Zone.BATTLEFIELD and hits["p3"].controller_id == "p1"
    assert is_borg_artifact_creature(hits["p3"])
    assert hits["p2"].zone == Zone.LIBRARY and p2.library[0] is hits["p2"]  # bottom of its own owner's library
    assert hits["p2"] not in p1.library

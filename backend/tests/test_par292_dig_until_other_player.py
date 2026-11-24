"""PAR-292 M14: "reveal cards from the top of their library until ..." dug by a player other than the controller
(RULE 701.20a, 110.2, 401.3): "<its controller | that player | target player> reveals cards from the top of their
library until they reveal a <quality> card, puts that card onto the battlefield / into their graveyard, then shuffles
the rest / puts the rest on the bottom", plus the own-library "put all cards revealed this way into your hand".

Every claimed card runs on a real GameEngine with bystanders: the ability controller's library must stay untouched when
an opponent digs, the found card enters under the digger, and the rest goes where the text says."""

from __future__ import annotations

import pytest

from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.catalogue.clause_hooks import match_clause
from tests.support.deck_batch import RICH, activate, card, cast, filler, game, stack_library

from tests.test_par292_dynamic_search_qualities import _modeled


@pytest.mark.parametrize("name", [
    "Chaos Mutation", "Divergent Transformations", "Destroy the Evidence", "Balustrade Spy",
    "Undercity Informer", "Transmogrify", "Polymorph", "Treasure Hunt", "Consuming Aberration",
])
def test_claimed_cards_are_modeled(name):
    assert _modeled(name)


@pytest.mark.parametrize("name", [
    # "in any order" is the player's own sequence (BUG-80): not claimed under the random-order wording
    "Proteus Staff",
    # a counted dig / a life loss equal to the hit's mana value (the controller-takes-it wording is M15's file)
    "Tasha, Unholy Archmage", "Jhoira, Weatherlight Corsair",
    # a counted dig / a hit quality measured against another object
    "Mind Funeral", "Wild Magic Surge", "Chaotic Transformation", "Reweave",
    # the controller sacrifices a targeted permanent first: no row for that head
    "Shape Anew",
])
def test_near_misses_stay_unclaimed(name):
    assert not _modeled(name)


def test_a_controller_wording_needs_a_previous_clause_that_took_a_permanent():
    text = ("its controller reveals cards from the top of their library until they reveal a creature card, "
            "puts that card onto the battlefield, then shuffles the rest into their library")
    assert match_clause(text) is None  # standalone, nothing for "its controller" to point back at


def test_any_order_bottom_is_not_read_as_random():
    assert match_clause(
        "target player reveals cards from the top of their library until they reveal a creature card. "
        "that player puts that card onto the battlefield and the rest on the bottom of their library in any order"
    ) is None


def _stack(eng, player, kinds):
    """Stack ``player``'s library top-down with one synthetic card per kind in ``kinds`` (first = top)."""
    sized = {"power": 1, "toughness": 1}  # a creature with no toughness would die the moment it entered
    cards = [
        filler(eng, f"{player}-{i}-{kind}", type_line=kind, player=player, zone=Zone.LIBRARY,
               **(sized if kind == "Creature" else {}))
        for i, kind in enumerate(kinds)
    ]
    stack_library(eng, player, *reversed(cards))
    return cards


def _snapshot(eng, player):
    p = eng.state.player_by_id(player)
    return list(p.library), list(p.hand)


def test_blessed_reincarnation_the_opponent_digs_their_own_library_and_shuffles_the_rest():
    eng = game(library=4)
    victim = filler(eng, "Victim", type_line="Creature", power=1, toughness=1, player="p2")
    mine_before = _snapshot(eng, "p1")
    revealed = _stack(eng, "p2", ["Land", "Instant", "Creature"])
    hit = revealed[2]
    cast(eng, card(eng, "Blessed Reincarnation", zone=Zone.HAND, without=True), targets=[victim])
    assert hit in eng.state.battlefield and hit.controller_id == "p2" and hit.owner_id == "p2"
    assert victim not in eng.state.battlefield
    p2 = eng.state.player_by_id("p2")
    assert hit not in p2.library
    assert revealed[0] in p2.library and revealed[1] in p2.library  # the rest went back into their own library
    assert _snapshot(eng, "p1") == mine_before  # the caster's library, hand and graveyard are untouched


def test_chaos_mutation_each_exiled_creatures_controller_digs_and_the_rest_goes_to_the_bottom():
    eng = game(library=4)
    mine = filler(eng, "Mine", type_line="Creature", power=1, toughness=1, player="p1")
    theirs = filler(eng, "Theirs", type_line="Creature", power=1, toughness=1, player="p2")
    mine_cards = _stack(eng, "p1", ["Land", "Creature"])
    their_cards = _stack(eng, "p2", ["Artifact", "Land", "Creature"])
    p1_size, p2_size = len(eng.state.player_by_id("p1").library), len(eng.state.player_by_id("p2").library)
    cast(eng, card(eng, "Chaos Mutation", zone=Zone.HAND), targets=[mine, theirs])
    assert mine_cards[1] in eng.state.battlefield and mine_cards[1].controller_id == "p1"
    assert their_cards[2] in eng.state.battlefield and their_cards[2].controller_id == "p2"
    assert len(eng.state.player_by_id("p1").library) == p1_size - 1  # only the hit left each library
    assert len(eng.state.player_by_id("p2").library) == p2_size - 1
    # RULE 401.4: the revealed non-hits sit together at the bottom (a random order among themselves).
    assert set(eng.state.player_by_id("p2").library[:2]) == {their_cards[0], their_cards[1]}
    assert set(eng.state.player_by_id("p1").library[:1]) == {mine_cards[0]}


def test_divergent_transformations_two_targets_two_diggers_rest_shuffled():
    eng = game(library=4)
    mine = filler(eng, "Mine", type_line="Creature", power=1, toughness=1, player="p1")
    theirs = filler(eng, "Theirs", type_line="Creature", power=1, toughness=1, player="p2")
    mine_cards = _stack(eng, "p1", ["Instant", "Creature"])
    their_cards = _stack(eng, "p2", ["Creature"])
    cast(eng, card(eng, "Divergent Transformations", zone=Zone.HAND), targets=[mine, theirs])
    assert mine_cards[1] in eng.state.battlefield and mine_cards[1].controller_id == "p1"
    assert their_cards[0] in eng.state.battlefield and their_cards[0].controller_id == "p2"
    assert mine_cards[0] in eng.state.player_by_id("p1").library
    assert mine not in eng.state.battlefield and theirs not in eng.state.battlefield


def test_destroy_the_evidence_hit_and_rest_all_go_to_the_controllers_graveyard():
    eng = game(library=4)
    land = filler(eng, "Their Land", type_line="Land", player="p2")
    cards = _stack(eng, "p2", ["Creature", "Instant", "Land"])
    mine_before = _snapshot(eng, "p1")
    cast(eng, card(eng, "Destroy the Evidence", zone=Zone.HAND), targets=[land])
    p2 = eng.state.player_by_id("p2")
    assert all(c in p2.graveyard for c in cards)  # the land hit goes with the rest
    assert land in p2.graveyard
    assert not any(c in p2.library for c in cards)
    assert _snapshot(eng, "p1") == mine_before


def test_destroy_the_evidence_with_no_land_to_find_mills_the_whole_library():
    eng = game(library=0)
    land = filler(eng, "Their Land", type_line="Land", player="p2")
    cards = _stack(eng, "p2", ["Creature", "Instant"])
    cast(eng, card(eng, "Destroy the Evidence", zone=Zone.HAND), targets=[land])
    p2 = eng.state.player_by_id("p2")
    assert all(c in p2.graveyard for c in cards) and not p2.library


def test_undercity_informer_target_player_digs_not_the_controller():
    eng = game(library=4)
    informer = card(eng, "Undercity Informer")
    fodder = filler(eng, "Fodder", type_line="Creature", power=1, toughness=1)
    cards = _stack(eng, "p2", ["Artifact", "Land", "Creature"])
    mine_before = _snapshot(eng, "p1")
    eng.state.player_by_id("p1").mana_pool.add_many(RICH)
    activate(eng, informer, targets=[eng.state.player_by_id("p2")], sacrifice_choice=fodder.instance_id)
    p2 = eng.state.player_by_id("p2")
    assert cards[0] in p2.graveyard and cards[1] in p2.graveyard  # revealed up to and including the land
    assert cards[2] in p2.library  # never reached
    assert _snapshot(eng, "p1") == mine_before


def test_treasure_hunt_puts_every_revealed_card_into_the_casters_hand():
    eng = game(library=4)
    cards = _stack(eng, "p1", ["Land", "Land", "Creature", "Land"])
    other_before = _snapshot(eng, "p2")
    cast(eng, card(eng, "Treasure Hunt", zone=Zone.HAND))
    p1 = eng.state.player_by_id("p1")
    assert all(c in p1.hand for c in cards[:3])  # up to and including the first nonland card, all of them
    assert cards[3] in p1.library
    assert _snapshot(eng, "p2") == other_before


def test_consuming_aberration_each_opponent_digs_their_own_library_and_the_controller_does_not():
    # "each opponent reveals ..." reaches the row through the player-scope adapter, which hands each iterated player
    # in as the dug player; the controller's own library stays untouched (RULE 101.4, 701.20a).
    eng = game(players=3, library=4)
    # its toughness is the card count of the opponents' graveyards: seed one so it survives until the trigger resolves
    filler(eng, "Seed", type_line="Sorcery", player="p2", zone=Zone.GRAVEYARD)
    aberration = card(eng, "Consuming Aberration")
    p2_cards = _stack(eng, "p2", ["Creature", "Land", "Instant"])
    p3_cards = _stack(eng, "p3", ["Instant", "Artifact", "Land", "Creature"])
    mine_before = _snapshot(eng, "p1")
    cast(eng, filler(eng, "Spell", type_line="Sorcery", zone=Zone.HAND, power=None))
    assert aberration in eng.state.battlefield
    p2 = eng.state.player_by_id("p2")
    p3 = eng.state.player_by_id("p3")
    assert p2_cards[0] in p2.graveyard and p2_cards[1] in p2.graveyard and p2_cards[2] in p2.library
    assert all(c in p3.graveyard for c in p3_cards[:3]) and p3_cards[3] in p3.library
    assert _snapshot(eng, "p1") == mine_before

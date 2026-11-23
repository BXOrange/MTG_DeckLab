"""PAR-292 M15: a card revealed from another player's library "until ..." that the ABILITY CONTROLLER puts onto the
battlefield under their control (RULE 110.2a, 108.3, 701.20a) -- Telemin Performance, Curse of Unbinding, Sméagol.

The dug player keeps ownership (the card returns to their zones when it leaves) and loses the card from their library; the
rest goes where the text says; the controller's own library and the digger's non-hit cards are the bystanders."""

from __future__ import annotations

import pytest

from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.parser.oracle.catalogue.clause_hooks import match_clause
from tests.support.deck_batch import RICH, activate, answer, card, cast, filler, game, pick_label, stack_library

from tests.test_par292_dynamic_search_qualities import _modeled


@pytest.mark.parametrize("name", ["Telemin Performance", "Curse of Unbinding", "Sméagol, Helpful Guide", "Browse"])
def test_claimed_cards_are_modeled(name):
    assert _modeled(name)


@pytest.mark.parametrize("name", [
    # a counted dig, three hits
    "Tasha, Unholy Archmage",
    # "whichever comes first" X-bounded dig plus a conditional sacrifice
    "Thought Dissector",
    # an X-bounded hit quality and an eminence activation from the command zone
    "M'Odo, the Gnarled Oracle",
    # the life loss equal to the hit's mana value
    "Jhoira, Weatherlight Corsair",
])
def test_near_misses_stay_unclaimed(name):
    assert not _modeled(name)


def test_the_non_hit_group_must_name_the_dug_type():
    assert match_clause(
        "target opponent reveals cards from the top of their library until they reveal a creature card. that player "
        "puts all noncreature cards revealed this way into their graveyard, then you put the creature card onto the "
        "battlefield under your control"
    ) is not None
    assert match_clause(
        "target opponent reveals cards from the top of their library until they reveal a creature card. that player "
        "puts all nonland cards revealed this way into their graveyard, then you put the creature card onto the "
        "battlefield under your control"
    ) is None


def test_the_rest_wording_must_be_one_of_the_printed_destinations():
    assert match_clause(
        "target opponent reveals cards from the top of their library until they reveal a creature card. put that card "
        "onto the battlefield under your control and the rest into their hand"
    ) is None


def _stack(eng, player, kinds):
    sized = {"power": 1, "toughness": 1}
    cards = [
        filler(eng, f"{player}-{i}-{kind}", type_line=kind, player=player, zone=Zone.LIBRARY,
               **(sized if kind == "Creature" else {}))
        for i, kind in enumerate(kinds)
    ]
    stack_library(eng, player, *reversed(cards))
    return cards


def test_telemin_performance_steals_the_creature_and_graveyards_the_rest_of_the_dug_cards():
    eng = game(players=3, library=4)
    their_cards = _stack(eng, "p2", ["Land", "Instant", "Creature", "Land"])
    bystander_cards = _stack(eng, "p3", ["Creature", "Land"])
    mine_before = list(eng.state.player_by_id("p1").library)
    cast(eng, card(eng, "Telemin Performance", zone=Zone.HAND), targets=[eng.state.player_by_id("p2")])
    hit = their_cards[2]
    p2 = eng.state.player_by_id("p2")
    assert hit in eng.state.battlefield
    assert hit.controller_id == "p1" and hit.owner_id == "p2"  # RULE 110.2a: stolen, but still the opponent's card
    assert their_cards[0] in p2.graveyard and their_cards[1] in p2.graveyard  # the dug-past cards
    assert their_cards[3] in p2.library and hit not in p2.library  # never reached / left
    assert list(eng.state.player_by_id("p1").library) == mine_before
    p3 = eng.state.player_by_id("p3")
    assert all(c in p3.library for c in bystander_cards)  # the third player's library was never touched


def test_a_stolen_card_goes_to_its_owners_graveyard_when_it_dies():
    eng = game(library=4)
    their_cards = _stack(eng, "p2", ["Creature"])
    cast(eng, card(eng, "Telemin Performance", zone=Zone.HAND), targets=[eng.state.player_by_id("p2")])
    hit = their_cards[0]
    assert hit.controller_id == "p1"
    eng.rules.put_into_graveyard(hit)
    assert hit in eng.state.player_by_id("p2").graveyard and hit not in eng.state.player_by_id("p1").graveyard


def test_telemin_performance_with_no_creature_graveyards_the_whole_library():
    eng = game(library=0)
    cards = _stack(eng, "p2", ["Land", "Instant"])
    cast(eng, card(eng, "Telemin Performance", zone=Zone.HAND), targets=[eng.state.player_by_id("p2")])
    p2 = eng.state.player_by_id("p2")
    assert all(c in p2.graveyard for c in cards) and not p2.library
    assert not any(o.owner_id == "p2" for o in eng.state.battlefield)


def test_curse_of_unbinding_the_enchanted_players_upkeep_digs_their_library_for_the_curses_controller():
    eng = game(library=4)
    curse = card(eng, "Curse of Unbinding")
    curse.attached_to = "p2"
    cards = _stack(eng, "p2", ["Land", "Creature", "Instant"])
    mine_before = (list(eng.state.player_by_id("p1").library), list(eng.state.player_by_id("p1").graveyard))
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep"))  # p1's own upkeep: not the enchanted player's
    eng.resolve_until_stable()
    assert all(c in eng.state.player_by_id("p2").library for c in cards)
    eng.state.active_player_index = 1  # p2's upkeep
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep"))
    eng.resolve_until_stable()
    p2 = eng.state.player_by_id("p2")
    assert cards[1] in eng.state.battlefield and cards[1].controller_id == "p1" and cards[1].owner_id == "p2"
    assert cards[0] in p2.graveyard
    assert cards[2] in p2.library
    assert (list(eng.state.player_by_id("p1").library), list(eng.state.player_by_id("p1").graveyard)) == mine_before


def test_smeagol_the_ring_tempted_player_digs_an_opponents_library_for_a_tapped_land():
    eng = game(library=4)
    smeagol = card(eng, "Sméagol, Helpful Guide")
    cards = _stack(eng, "p2", ["Creature", "Land", "Instant"])
    mine_before = (list(eng.state.player_by_id("p1").library), list(eng.state.player_by_id("p1").graveyard))
    eng.state.fire_event(GameEvent(EventType.RING_TEMPTED, player_id="p1"))
    eng.resolve_until_stable()
    eng.resolve_pending_choice("p2")  # RULE 115.1: "target opponent" is chosen when the trigger is put on the stack
    eng.resolve_until_stable()
    p2 = eng.state.player_by_id("p2")
    land = cards[1]
    assert land in eng.state.battlefield and land.tapped and land.controller_id == "p1" and land.owner_id == "p2"
    assert cards[0] in p2.graveyard  # "the rest into their graveyard"
    assert cards[2] in p2.library
    assert (list(eng.state.player_by_id("p1").library), list(eng.state.player_by_id("p1").graveyard)) == mine_before
    assert smeagol in eng.state.battlefield


def test_smeagol_does_not_dig_when_an_opponent_is_tempted():
    eng = game(library=4)
    card(eng, "Sméagol, Helpful Guide")
    cards = _stack(eng, "p2", ["Land", "Creature"])
    eng.state.fire_event(GameEvent(EventType.RING_TEMPTED, player_id="p2"))
    eng.resolve_until_stable()
    assert all(c in eng.state.player_by_id("p2").library for c in cards)


def test_browse_puts_the_picked_card_into_the_hand_and_exiles_the_other_four():
    # "Look at the top five cards of your library, put one of them into your hand, and exile the rest." (RULE 406.3)
    eng = game(library=8)
    cards = _stack(eng, "p1", ["Land", "Creature", "Instant", "Land", "Sorcery", "Land"])
    bystander = _stack(eng, "p2", ["Land", "Creature"])
    browse = card(eng, "Browse")
    eng.state.player_by_id("p1").mana_pool.add_many(RICH)
    hand_before = list(eng.state.player_by_id("p1").hand)
    activate(eng, browse)
    answer(eng, pick_label(cards[2].name))
    p1 = eng.state.player_by_id("p1")
    assert cards[2] in p1.hand and set(p1.hand) == set(hand_before) | {cards[2]}
    assert all(c in p1.exile for c in (cards[0], cards[1], cards[3], cards[4]))  # the unpicked cards of the five
    assert cards[5] in p1.library  # the sixth card was never looked at
    assert all(c in eng.state.player_by_id("p2").library for c in bystander)


@pytest.mark.parametrize("text", [
    # a counted pick that is not one card, an unknown rest verb, a destination the grammar does not know
    "look at the top 5 cards of your library, put 1 of them into your hand, and discard the rest",
    "look at the top 5 cards of your library, put 1 of them into your hand, and exile them",
])
def test_the_comma_spelling_refuses_other_rest_verbs(text):
    assert match_clause(text) is None

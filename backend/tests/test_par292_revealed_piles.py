"""PAR-292 M21: the top of a library divided into two piles (RULE 700.3, 101.4, 701.20, 608.2d).

"Reveal the top N cards of your library. An opponent separates those cards into two piles. Put one pile into your hand
and the other into your graveyard." (Sphinx of Uthuun), "...and separate them into 2 piles. An opponent chooses 1 of
those piles" (Steam Augury, Epiphany at the Drownyard), "look at the top N cards ... separate them into a face-down pile
and a face-up pile" (Curator of Destinies, Riddles in the Dark, Atris, Fortune's Favor, Sauron's Ransom).

Run on a real engine with bystanders: the right player separates, the right player chooses, both piles land where
printed, the card below the revealed ones stays in the library, and a face-down pile shows the chooser only its size."""

from __future__ import annotations

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle

from tests.support.deck_batch import cast, card, filler, game, put_on_battlefield, stack_library
from tests.test_par292_dynamic_search_qualities import _modeled

CLAIMED = ["Fact or Fiction", "Sphinx of Uthuun", "Sphinx of Clear Skies", "Steam Augury", "Epiphany at the Drownyard",
           "Curator of Destinies", "Riddles in the Dark", "Atris, Oracle of Half-Truths", "Fortune's Favor",
           "Sauron's Ransom"]


@pytest.mark.parametrize("name", CLAIMED)
def test_claimed_cards_are_modeled(name):
    assert _modeled(name)


def _probe(text):
    return parse_oracle(Card(id="t", name="Probe", type_line="Sorcery", oracle_text=text))


@pytest.mark.parametrize("text", [
    # the destinations are the printed hand and graveyard only
    "Reveal the top five cards of your library. An opponent separates those cards into two piles. "
    "Put one pile into your hand and the other on the bottom of your library.",
    # an announced X without a measure is not a number the effect can read under a trigger
    "Reveal the top X cards of your library. An opponent separates those cards into two piles. "
    "Put one pile into your hand and the other into your graveyard.",
    # the chooser must be an opponent
    "Reveal the top five cards of your library and separate them into two piles. You choose one of those piles. "
    "Put that pile into your hand and the other into your graveyard.",
])
def test_near_misses_stay_unmodeled(text):
    assert not _probe(text).modeled


def _library(eng, n=5, player="p1"):
    cards = [filler(eng, f"Top{i}", type_line="Instant", player=player, zone=Zone.LIBRARY) for i in range(n)]
    below = filler(eng, "Below", type_line="Instant", player=player, zone=Zone.LIBRARY)
    stack_library(eng, player, below, *reversed(cards))  # cards[0] is the top
    return cards, below


def _names(eng, zone, player="p1"):
    return sorted(o.name for o in getattr(eng.state.player_by_id(player), zone))


def _answer(eng, who, option):
    assert eng.state.pending_choice["player_id"] == who
    eng.resolve_pending_choice(option)


def test_opponent_separates_and_the_caster_chooses():
    eng = game(library=0)
    top, below = _library(eng)
    bystander = filler(eng, "TheirCard", type_line="Instant", player="p2", zone=Zone.LIBRARY)
    cast(eng, card(eng, "Steam Augury", zone=Zone.HAND))
    # Steam Augury: the caster separates, an opponent chooses
    _answer(eng, "p1", str(top[0].instance_id))
    _answer(eng, "p1", str(top[1].instance_id))
    _answer(eng, "p1", "decline")
    choice = eng.state.pending_choice
    assert choice["player_id"] == "p2"
    assert [o["label"] for o in choice["options"]] == ["Top0, Top1", "Top2, Top3, Top4"]
    _answer(eng, "p2", "second")
    assert _names(eng, "hand") == ["Top2", "Top3", "Top4"]
    assert _names(eng, "graveyard") == ["Steam Augury", "Top0", "Top1"]
    assert below in eng.state.player_by_id("p1").library and bystander.zone == Zone.LIBRARY


def test_sphinx_of_uthuun_opponent_separates_caster_chooses():
    eng = game(library=0)
    top, below = _library(eng)
    put_on_battlefield(eng, "Sphinx of Uthuun")
    eng.resolve_until_stable()
    _answer(eng, "p2", str(top[4].instance_id))
    _answer(eng, "p2", "decline")
    assert eng.state.pending_choice["player_id"] == "p1"
    _answer(eng, "p1", "first")
    assert _names(eng, "hand") == ["Top4"]
    assert _names(eng, "graveyard") == ["Top0", "Top1", "Top2", "Top3"]
    assert below.zone == Zone.LIBRARY


def test_epiphany_reveals_x_plus_one_cards():
    eng = game(library=0)
    top, below = _library(eng, 6)
    spell = card(eng, "Epiphany at the Drownyard", zone=Zone.HAND)
    cast(eng, spell, x=2)
    choice = eng.state.pending_choice
    assert choice["player_id"] == "p1" and len(choice["options"]) == 3 + 1  # X + 1 = 3 revealed cards, plus "decline"
    _answer(eng, "p1", "decline")
    _answer(eng, "p2", "second")  # the first pile is empty, so the second (all three) goes to the hand
    assert _names(eng, "hand") == ["Top0", "Top1", "Top2"]
    assert below.zone == Zone.LIBRARY and top[3].zone == Zone.LIBRARY


def test_clear_skies_counts_basic_land_types():
    eng = game(library=0)
    top, _ = _library(eng, 5)
    filler(eng, "Isle", type_line="Basic Land — Island")
    filler(eng, "Swamp1", type_line="Basic Land — Swamp")
    filler(eng, "Swamp2", type_line="Basic Land — Swamp")
    put_on_battlefield(eng, "Sphinx of Clear Skies")
    eng.recompute_continuous_effects()
    sphinx = next(o for o in eng.state.battlefield if o.name == "Sphinx of Clear Skies")
    eng.rules.deal_combat_damage([(eng.state.player_by_id("p2"), 3, sphinx)])
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["player_id"] == "p2"
    assert len(choice["options"]) == 2 + 1  # two basic land types among the lands, plus "decline"


def test_curator_face_down_pile_shows_the_opponent_only_its_size():
    eng = game(library=0)
    top, below = _library(eng)
    put_on_battlefield(eng, "Curator of Destinies")
    eng.resolve_until_stable()
    _answer(eng, "p1", str(top[0].instance_id))
    _answer(eng, "p1", str(top[1].instance_id))
    _answer(eng, "p1", "decline")
    choice = eng.state.pending_choice
    assert choice["player_id"] == "p2"
    labels = [o["label"] for o in choice["options"]]
    assert labels == ["Top0, Top1", "Verdeckter Stapel (3)"]  # the face-up pile's cards, the face-down pile's size
    _answer(eng, "p2", "second")
    assert _names(eng, "hand") == ["Top2", "Top3", "Top4"]
    assert _names(eng, "graveyard") == ["Top0", "Top1"]
    assert not any(ev.type == EventType.REVEAL for ev in eng.state.events_this_turn())  # looked at, never revealed
    assert below.zone == Zone.LIBRARY


def test_fortunes_favor_opponent_target_separates_and_caster_chooses():
    eng = game(library=0, players=3)
    top, below = _library(eng, 4)
    spell = card(eng, "Fortune's Favor", zone=Zone.HAND)
    cast(eng, spell, targets=[eng.state.player_by_id("p3")])
    _answer(eng, "p3", str(top[0].instance_id))  # the targeted opponent, not p2
    _answer(eng, "p3", "decline")
    choice = eng.state.pending_choice
    assert choice["player_id"] == "p1"
    assert [o["label"] for o in choice["options"]] == ["Top0", "Verdeckter Stapel (3)"]
    _answer(eng, "p1", "second")
    assert _names(eng, "hand") == ["Top1", "Top2", "Top3"]
    assert _names(eng, "graveyard") == ["Fortune's Favor", "Top0"]
    assert below.zone == Zone.LIBRARY


def test_sauron_ransom_picks_an_opponent_then_the_ring_tempts():
    eng = game(library=0, players=3)
    top, _ = _library(eng, 4)
    cast(eng, card(eng, "Sauron's Ransom", zone=Zone.HAND))
    assert eng.state.pending_choice["player_id"] == "p1" and eng.state.pending_choice["kind"] == "choose_pile_divider"
    _answer(eng, "p1", "p3")
    _answer(eng, "p3", "decline")  # every card in the face-down pile
    _answer(eng, "p1", "second")
    assert _names(eng, "hand") == ["Top0", "Top1", "Top2", "Top3"]


def test_the_wrong_player_cannot_answer():
    eng = game(library=0)
    _library(eng)
    put_on_battlefield(eng, "Curator of Destinies")
    eng.resolve_until_stable()
    assert eng.state.pending_choice["player_id"] == "p1"
    with pytest.raises(Exception):
        eng.resolve_pending_choice("decline", player_id="p2")

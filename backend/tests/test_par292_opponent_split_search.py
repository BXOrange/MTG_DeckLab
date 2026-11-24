"""PAR-292 M17: "search your library for up to N <cards> with different names/powers and reveal them. An opponent chooses
M of those cards. Put the chosen cards <A> and the rest <B>" (RULE 701.19, 701.20, 608.2d, 101.4).

Elemental Teachings / Realms Uncharted / Threats Undetected / Ecological Appreciation on a real GameEngine: the caster
picks the found cards, an *opponent* (never the caster) chooses which are the chosen pile, the piles go to their
destinations and the library is shuffled once. Every test carries bystanders (cards that do not match stay put)."""
import pytest

from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import activate, card, cast, filler, game, put_on_battlefield
from tests.test_par292_dynamic_search_qualities import _modeled, _offered

NAMES = ["Elemental Teachings", "Realms Uncharted", "Threats Undetected", "Ecological Appreciation", "The Karst, Enchanted", "Burning-Rune Demon"]


@pytest.mark.parametrize("name", NAMES)
def test_claimed_cards_are_modeled(name):
    assert _modeled(name)


def _shuffles(eng):
    shuffled: list[str] = []
    original = eng.rules.shuffle_library

    def spy(player):
        shuffled.append(player.id)
        return original(player)

    eng.rules.shuffle_library = spy
    return shuffled


def _land(eng, name, player="p1", zone=Zone.LIBRARY):
    return filler(eng, name, type_line="Basic Land — Forest", player=player, zone=zone)


def _pick(eng, label):
    choice = eng.state.pending_choice
    eng.resolve_pending_choice(str(next(o["id"] for o in choice["options"] if o["label"] == label)))


def _find_four(eng, labels):
    for label in labels:
        _pick(eng, label)


def _names(eng, zone, player="p1"):
    return sorted(o.name for o in getattr(eng.state.player_by_id(player), zone))


def _lands_library(eng):
    for name in ("Aa", "Bb", "Cc", "Dd", "Ee"):
        _land(eng, name)
    _land(eng, "Aa")  # a second copy of a name: refused once "Aa" is found
    filler(eng, "Bystander", type_line="Creature", power=1, toughness=1, zone=Zone.LIBRARY)


def test_teachings_offers_only_lands_with_different_names_and_the_opponent_splits():
    eng = game(library=0)
    _lands_library(eng)
    shuffled = _shuffles(eng)
    cast(eng, card(eng, "Elemental Teachings", zone=Zone.HAND))
    assert eng.state.pending_choice["player_id"] == "p1"
    assert _offered(eng) == {"Aa", "Bb", "Cc", "Dd", "Ee"}  # the creature is not a land card
    _pick(eng, "Aa")
    assert _offered(eng) == {"Bb", "Cc", "Dd", "Ee"}  # the second "Aa" shares a name with a found card
    _find_four(eng, ["Bb", "Cc", "Dd"])
    split = eng.state.pending_choice
    assert split["kind"] == "intuition_choose" and split["player_id"] == "p2"  # the opponent, not the caster
    assert sorted(o["label"] for o in split["options"]) == ["Aa", "Bb", "Cc", "Dd"]
    assert [o.name for o in eng.state.battlefield if o.is_land and o.controller_id == "p1"] == []  # nothing moved yet
    assert shuffled == []
    _pick(eng, "Aa")
    _pick(eng, "Bb")
    assert eng.state.pending_choice is None
    assert _names(eng, "graveyard") == ["Aa", "Bb", "Elemental Teachings"]  # the chosen pile
    lands = [o for o in eng.state.battlefield if o.name in {"Cc", "Dd"}]
    assert sorted(o.name for o in lands) == ["Cc", "Dd"] and all(o.tapped for o in lands)  # the rest, tapped
    assert _names(eng, "library") == ["Aa", "Bystander", "Ee"]  # unfound cards stay, the duplicate name too
    assert shuffled == ["p1"]  # one shuffle


def test_the_caster_cannot_answer_the_opponents_split():
    eng = game(library=0)
    _lands_library(eng)
    cast(eng, card(eng, "Realms Uncharted", zone=Zone.HAND))
    _find_four(eng, ["Aa", "Bb", "Cc", "Dd"])
    assert eng.state.pending_choice["player_id"] == "p2"


def test_realms_uncharted_sends_the_rest_to_the_hand():
    eng = game(library=0)
    _lands_library(eng)
    cast(eng, card(eng, "Realms Uncharted", zone=Zone.HAND))
    _find_four(eng, ["Aa", "Bb", "Cc", "Dd"])
    _pick(eng, "Cc")
    _pick(eng, "Dd")
    assert _names(eng, "graveyard") == ["Cc", "Dd", "Realms Uncharted"]
    assert _names(eng, "hand") == ["Aa", "Bb"]
    assert [o for o in eng.state.battlefield if o.is_land and o.controller_id == "p1"] == []


def test_fewer_found_cards_than_the_chosen_count_are_all_chosen():
    eng = game(library=0)
    _land(eng, "Aa")
    filler(eng, "Bystander", type_line="Creature", power=1, toughness=1, zone=Zone.LIBRARY)
    cast(eng, card(eng, "Realms Uncharted", zone=Zone.HAND))
    _pick(eng, "Aa")  # nothing else matches, so the search ends by itself
    assert eng.state.pending_choice["player_id"] == "p2"
    _pick(eng, "Aa")  # "chooses two" of a single found card: that card is the chosen pile
    assert _names(eng, "graveyard") == ["Aa", "Realms Uncharted"]
    assert _names(eng, "library") == ["Bystander"]


def test_threats_undetected_needs_different_powers_and_shuffles_the_chosen_cards_back():
    eng = game(library=0)
    for name, power in (("P2a", 2), ("P2b", 2), ("P3", 3), ("P4", 4), ("P5", 5)):
        filler(eng, name, type_line="Creature", power=power, toughness=1, zone=Zone.LIBRARY)
    filler(eng, "LandBystander", type_line="Basic Land — Forest", zone=Zone.LIBRARY)
    shuffled = _shuffles(eng)
    cast(eng, card(eng, "Threats Undetected", zone=Zone.HAND))
    assert _offered(eng) == {"P2a", "P2b", "P3", "P4", "P5"}
    _pick(eng, "P2a")
    assert _offered(eng) == {"P3", "P4", "P5"}  # P2b shares power 2
    _find_four(eng, ["P3", "P4", "P5"])
    assert eng.state.pending_choice["player_id"] == "p2"
    _pick(eng, "P2a")
    _pick(eng, "P5")
    assert _names(eng, "hand") == ["P3", "P4"]  # the rest
    assert _names(eng, "library") == ["LandBystander", "P2a", "P2b", "P5"]  # the chosen two went back in
    assert shuffled == ["p1"]


def test_ecological_appreciation_searches_the_graveyard_too_and_exiles_itself():
    eng = game(library=0)
    filler(eng, "InLibrary", type_line="Creature", mv=2, power=1, toughness=1, zone=Zone.LIBRARY)
    filler(eng, "InGraveyard", type_line="Creature", mv=3, power=1, toughness=1, zone=Zone.GRAVEYARD)
    filler(eng, "TooBig", type_line="Creature", mv=4, power=1, toughness=1, zone=Zone.LIBRARY)
    filler(eng, "NotACreature", type_line="Artifact", mv=1, zone=Zone.LIBRARY)
    filler(eng, "Dup", type_line="Creature", mv=1, power=1, toughness=1, zone=Zone.LIBRARY)
    filler(eng, "Dup", type_line="Creature", mv=1, power=1, toughness=1, zone=Zone.GRAVEYARD)
    shuffled = _shuffles(eng)
    spell = card(eng, "Ecological Appreciation", zone=Zone.HAND)
    cast(eng, spell, x=3)
    assert _offered(eng) == {"InLibrary", "InGraveyard", "Dup"}  # mana value 3 or less, creature cards only
    _pick(eng, "Dup")
    assert _offered(eng) == {"InLibrary", "InGraveyard"}  # the other "Dup" shares a name
    _pick(eng, "InLibrary")
    _pick(eng, "InGraveyard")  # nothing else is eligible (TooBig, the artifact, the second Dup), so the search ends
    split = eng.state.pending_choice
    assert split["player_id"] == "p2"
    _pick(eng, "Dup")
    _pick(eng, "InGraveyard")
    assert sorted(o.name for o in eng.state.battlefield if o.name == "InLibrary") == ["InLibrary"]
    assert "Dup" in _names(eng, "library") and "InGraveyard" in _names(eng, "library")  # chosen: shuffled in
    assert "TooBig" in _names(eng, "library") and "NotACreature" in _names(eng, "library")
    assert spell.zone == Zone.EXILE  # "Exile Ecological Appreciation."
    assert shuffled == ["p1"]


def test_in_a_multiplayer_game_the_caster_names_the_opponent_who_chooses():
    eng = game(players=3, library=0)
    _lands_library(eng)
    cast(eng, card(eng, "Realms Uncharted", zone=Zone.HAND))
    _find_four(eng, ["Aa", "Bb", "Cc", "Dd"])
    pick = eng.state.pending_choice
    assert pick["kind"] == "choose_opponent_decider" and pick["player_id"] == "p1"
    eng.resolve_pending_choice("p3")
    assert eng.state.pending_choice["kind"] == "intuition_choose"
    assert eng.state.pending_choice["player_id"] == "p3"  # only the chosen opponent
    _pick(eng, "Aa")
    _pick(eng, "Bb")
    assert eng.state.pending_choice is None
    assert _names(eng, "graveyard") == ["Aa", "Bb", "Realms Uncharted"]


def test_a_search_that_finds_nothing_still_shuffles_and_asks_nobody():
    eng = game(library=0)
    filler(eng, "Bystander", type_line="Creature", power=1, toughness=1, zone=Zone.LIBRARY)
    shuffled = _shuffles(eng)
    cast(eng, card(eng, "Elemental Teachings", zone=Zone.HAND))
    assert eng.state.pending_choice is None
    assert shuffled == ["p1"]
    assert _names(eng, "library") == ["Bystander"]


@pytest.mark.parametrize("text", [
    # a put-only split with no shuffle would shuffle when the card never says so
    "search your library for up to 4 land cards with different names and reveal them. an opponent chooses 2 of "
    "those cards. put the chosen cards into your graveyard and the rest into your hand",
    # the opponent chooses from more cards than are chosen
    "search your library for up to 2 land cards with different names and reveal them. an opponent chooses 2 of "
    "those cards. put the chosen cards into your graveyard and the rest into your hand, then shuffle",
    # a chooser the template does not name
    "search your library for up to 4 land cards with different names and reveal them. each opponent chooses 2 of "
    "those cards. put the chosen cards into your graveyard and the rest into your hand, then shuffle",
    # a destination the engine has no word for
    "search your library for up to 4 land cards with different names and reveal them. an opponent chooses 2 of "
    "those cards. put the chosen cards into your graveyard and the rest on top of your library, then shuffle",
])
def test_near_misses_stay_unclaimed(text):
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
    assert match_clause(text) is None


def _karst_library(eng):
    """Cards that pairwise share nothing, plus one that shares a card type, a name-different twin and a bystander."""
    filler(eng, "Cheap Land", type_line="Land", mv=0, zone=Zone.LIBRARY)
    filler(eng, "Bear", type_line="Creature", mv=2, power=2, toughness=2, zone=Zone.LIBRARY)
    filler(eng, "Rock", type_line="Artifact", mv=3, zone=Zone.LIBRARY)
    filler(eng, "Charm", type_line="Instant", mv=4, zone=Zone.LIBRARY)
    filler(eng, "Other Bear", type_line="Creature", mv=5, power=3, toughness=3, zone=Zone.LIBRARY)  # a creature, like Bear
    filler(eng, "Cheap Rock", type_line="Artifact", mv=2, zone=Zone.LIBRARY)  # the same mana value as Bear


def test_the_karst_finds_cards_that_share_no_value_or_type_and_the_targeted_opponent_chooses():
    eng = game(players=3, library=0)
    karst = card(eng, "The Karst, Enchanted")
    filler(eng, "Fodder", type_line="Creature", power=1, toughness=1)
    _karst_library(eng)
    eng.state.player_by_id("p1").mana_pool.add_many({"C": 3, "U": 1})
    activate(eng, karst, 0, targets=[eng.state.player_by_id("p3")])
    assert _offered(eng) == {"Cheap Land", "Bear", "Rock", "Charm", "Other Bear", "Cheap Rock"}
    _pick(eng, "Bear")
    assert _offered(eng) == {"Cheap Land", "Rock", "Charm"}  # no creature, no mana value 2 (Other Bear, Cheap Rock gone)
    _find_four(eng, ["Rock", "Charm", "Cheap Land"])
    split = eng.state.pending_choice
    assert split["kind"] == "intuition_choose" and split["player_id"] == "p3"  # the target, not p2, not the caster
    _pick(eng, "Bear")
    _pick(eng, "Rock")
    assert _names(eng, "graveyard") == ["Bear", "Fodder", "Rock"]
    assert _names(eng, "hand") == ["Charm", "Cheap Land"]
    assert _names(eng, "library") == ["Cheap Rock", "Other Bear"]


def _demon_library(eng):
    filler(eng, "Burning-Rune Demon", type_line="Creature — Demon", mv=4, power=6, toughness=6, zone=Zone.LIBRARY)  # a copy
    filler(eng, "Sol", type_line="Artifact", zone=Zone.LIBRARY)
    filler(eng, "Sol", type_line="Artifact", zone=Zone.LIBRARY)
    filler(eng, "Mox", type_line="Artifact", zone=Zone.LIBRARY)
    filler(eng, "Lotus", type_line="Artifact", zone=Zone.LIBRARY)


def test_burning_rune_demon_finds_exactly_two_differently_named_cards_not_named_itself():
    eng = game(library=0)
    _demon_library(eng)
    shuffled = _shuffles(eng)
    put_on_battlefield(eng, "Burning-Rune Demon")
    assert _offered(eng) == {"Sol", "Mox", "Lotus"}  # not another Burning-Rune Demon
    choice = eng.state.pending_choice
    assert any(o["id"] == "decline" for o in choice["options"])  # "you may search"
    _pick(eng, "Sol")
    choice = eng.state.pending_choice
    assert _offered(eng) == {"Mox", "Lotus"}  # the second Sol shares a name
    assert not any(o["id"] == "decline" for o in choice["options"])  # exactly two: no stopping at one
    with pytest.raises(ValueError):
        eng.resolve_pending_choice("decline")
    _pick(eng, "Mox")
    split = eng.state.pending_choice
    assert split["kind"] == "intuition_choose" and split["player_id"] == "p2"
    _pick(eng, "Mox")
    assert _names(eng, "hand") == ["Mox"] and _names(eng, "graveyard") == ["Sol"]  # the chosen card to hand
    assert _names(eng, "library") == ["Burning-Rune Demon", "Lotus", "Sol"]
    assert shuffled == ["p1"]


def test_burning_rune_demon_search_can_be_declined():
    eng = game(library=0)
    _demon_library(eng)
    put_on_battlefield(eng, "Burning-Rune Demon")
    eng.resolve_pending_choice("decline")
    assert eng.state.pending_choice is None
    assert _names(eng, "hand") == [] and _names(eng, "graveyard") == []
    assert len(eng.state.player_by_id("p1").library) == 5

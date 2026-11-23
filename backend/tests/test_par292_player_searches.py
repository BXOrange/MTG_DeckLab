"""PAR-292 M7: a library search made by a player other than the ability's controller (RULE 701.19a, 101.4).

"Each player / each opponent / each other player may search their library ...", "target player searches their
library ...", and "its controller searches their library ..." after a destroyed permanent. Every claimed card runs on a
real GameEngine: each acting player is offered only cards from their own library and answers for themselves."""
import pytest

from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import activate, answer, card, cast, filler, game, put_on_battlefield

from tests.test_par292_dynamic_search_qualities import _library_card, _modeled, _offered


@pytest.mark.parametrize("name", [
    "Jungle Wayfinder", "Old-Growth Dryads", "Veteran Explorer", "Fertilid", "Fertilid's Favor", "Field of Ruin",
    "Boldwyr Heavyweights", "Hired Giant", "Noble Benefactor", "Volatile Fault", "Magmatic Hellkite", "New Frontiers",
    "Weird Harvest", "Borderland Explorer", "Path to Exile", "Boseiju, Who Endures",
])
def test_claimed_cards_are_modeled(name):
    assert _modeled(name)


def _own_library(eng, player, prefix):
    """Two basic lands and a nonbasic land / spell bystanders in ``player``'s library."""
    _library_card(eng, f"{prefix}Plains", mv=0, type_line="Basic Land — Plains", player=player)
    _library_card(eng, f"{prefix}Swamp", mv=0, type_line="Basic Land — Swamp", player=player)
    _library_card(eng, f"{prefix}Nonbasic", mv=0, type_line="Land — Plains", player=player)
    _library_card(eng, f"{prefix}Spell", mv=2, type_line="Creature", player=player)


def _searcher(eng):
    return eng.state.pending_choice["player_id"]


def _pick(eng, label):
    choice = eng.state.pending_choice
    eng.resolve_pending_choice(str(next(o["id"] for o in choice["options"] if o["label"] == label)))


def test_jungle_wayfinder_lets_each_player_find_a_basic_land_from_their_own_library():
    eng = game(library=0)
    _own_library(eng, "p1", "A")
    _own_library(eng, "p2", "B")
    put_on_battlefield(eng, "Jungle Wayfinder")
    first = _searcher(eng)
    assert _offered(eng) == {f"{'A' if first == 'p1' else 'B'}Plains", f"{'A' if first == 'p1' else 'B'}Swamp"}
    _pick(eng, f"{'A' if first == 'p1' else 'B'}Swamp")
    second = _searcher(eng)
    assert second != first
    prefix = "A" if second == "p1" else "B"
    assert _offered(eng) == {f"{prefix}Plains", f"{prefix}Swamp"}  # no nonbasic land, no spell, nothing of the other
    _pick(eng, f"{prefix}Plains")
    assert eng.state.pending_choice is None
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    assert [o.name for o in p1.hand] and [o.name for o in p2.hand]
    assert {o.name[0] for o in p1.hand} == {"A"} and {o.name[0] for o in p2.hand} == {"B"}


def test_a_player_may_decline_their_own_search():
    eng = game(library=0)
    _own_library(eng, "p1", "A")
    _own_library(eng, "p2", "B")
    put_on_battlefield(eng, "Jungle Wayfinder")
    eng.resolve_pending_choice("decline")
    eng.resolve_pending_choice("decline")
    assert not eng.state.player_by_id("p1").hand and not eng.state.player_by_id("p2").hand


def test_old_growth_dryads_searches_only_for_opponents_and_enters_tapped_under_their_control():
    eng = game(library=0)
    _own_library(eng, "p1", "A")
    _own_library(eng, "p2", "B")
    put_on_battlefield(eng, "Old-Growth Dryads")
    assert _searcher(eng) == "p2"  # the controller does not search
    assert _offered(eng) == {"BPlains", "BSwamp"}
    _pick(eng, "BSwamp")
    assert eng.state.pending_choice is None
    found = next(o for o in eng.state.battlefield if o.name == "BSwamp")
    assert found.tapped and found.controller_id == "p2"
    assert not any(o.name.startswith("A") for o in eng.state.battlefield)  # p1's library untouched


def test_veteran_explorer_finds_up_to_two_basics_for_each_player_when_it_dies():
    eng = game(library=0)
    _own_library(eng, "p1", "A")
    _own_library(eng, "p2", "B")
    explorer = card(eng, "Veteran Explorer")
    eng.rules.destroy(explorer)
    eng.resolve_until_stable()
    names = []
    for _ in range(8):
        choice = eng.state.pending_choice
        if not choice:
            break
        opts = [o for o in choice["options"] if o["id"] != "decline"]
        if not opts:
            eng.resolve_pending_choice("decline")
            continue
        names.append(opts[0]["label"])
        eng.resolve_pending_choice(str(opts[0]["id"]))
    assert sorted(names) == ["APlains", "ASwamp", "BPlains", "BSwamp"]
    assert not any(o.name.endswith(("Nonbasic", "Spell")) for o in eng.state.battlefield)


def test_hired_giant_finds_a_land_for_each_other_player_only():
    eng = game(library=0)
    _own_library(eng, "p1", "A")
    _own_library(eng, "p2", "B")
    put_on_battlefield(eng, "Hired Giant")
    assert _searcher(eng) == "p2"
    assert _offered(eng) == {"BPlains", "BSwamp", "BNonbasic"}  # any land card, still only p2's own library
    _pick(eng, "BNonbasic")
    assert eng.state.pending_choice is None
    assert any(o.name == "BNonbasic" and o.controller_id == "p2" for o in eng.state.battlefield)


def test_fertilids_favor_lets_the_targeted_player_search_not_its_caster():
    eng = game(library=0)
    _own_library(eng, "p1", "A")
    _own_library(eng, "p2", "B")
    body = filler(eng, "Body", type_line="Creature", power=1, toughness=1)
    cast(eng, card(eng, "Fertilid's Favor", zone=Zone.HAND),
         targets=[eng.state.player_by_id("p2"), body])
    assert _searcher(eng) == "p2"
    assert _offered(eng) == {"BPlains", "BSwamp"}
    _pick(eng, "BPlains")
    assert any(o.name == "BPlains" and o.tapped and o.controller_id == "p2" for o in eng.state.battlefield)
    assert not any(o.name.startswith("A") for o in eng.state.battlefield)
    assert body.counters.get("+1/+1") == 2  # the second sentence still reaches its own target


def test_fertilids_favor_may_target_its_own_caster():
    eng = game(library=0)
    _own_library(eng, "p1", "A")
    _own_library(eng, "p2", "B")
    body = filler(eng, "Body", type_line="Creature", power=1, toughness=1)
    cast(eng, card(eng, "Fertilid's Favor", zone=Zone.HAND), targets=[eng.state.player_by_id("p1"), body])
    assert _searcher(eng) == "p1"
    assert _offered(eng) == {"APlains", "ASwamp"}


def test_magmatic_hellkite_gives_the_destroyed_lands_controller_a_stunned_basic():
    eng = game(library=0)
    _own_library(eng, "p1", "A")
    _own_library(eng, "p2", "B")
    filler(eng, "TheirNonbasic", type_line="Land — Plains", player="p2")
    filler(eng, "TheirBasic", type_line="Basic Land — Plains", player="p2")  # not a legal target: basic
    put_on_battlefield(eng, "Magmatic Hellkite")
    answer(eng, limit=1)  # the single legal target is picked automatically or with one answer
    if eng.state.pending_choice and eng.state.pending_choice["kind"] != "search":
        eng.resolve_pending_choice(str(eng.state.pending_choice["options"][0]["id"]))
    assert _searcher(eng) == "p2"  # its controller, not the Hellkite's controller
    assert _offered(eng) == {"BPlains", "BSwamp"}
    _pick(eng, "BSwamp")
    found = next(o for o in eng.state.battlefield if o.name == "BSwamp")
    assert found.tapped and found.counters.get("stun") == 1
    assert not any(o.name == "TheirNonbasic" for o in eng.state.battlefield)
    assert any(o.name == "TheirBasic" for o in eng.state.battlefield)  # the bystander basic survives


@pytest.mark.parametrize("text", [
    # a pronoun that is not the searcher's own (the rewording cannot make it the controller's search)
    "each player may search your library for a basic land card, put it onto the battlefield, then shuffle",
    # no shuffle instruction at all
    "each player may search their library for a basic land card, put it onto the battlefield",
    # a shuffle both in the tail and in a trailing sentence
    "each player may search their library for a basic land card, put it onto the battlefield, then shuffle. then each "
    "player who searched their library this way shuffles",
    # a referent-less "that player" (nothing earlier chose a permanent or player)
    "that player may search their library for a basic land card, put it onto the battlefield, then shuffle",
    # a rider the plain search does not read
    "each player may search their library for a basic land card, put it onto the battlefield, then shuffle and draw a card",
])
def test_player_search_refuses_near_miss_shapes(text):
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause

    assert match_clause(text) is None


def test_new_frontiers_finds_up_to_x_basics_for_each_player():
    """The spell's {X} reaches the per-player search ("up to X basic land cards")."""
    eng = game(library=0)
    for who in ("p1", "p2"):
        for i in range(3):
            _library_card(eng, f"{who}Basic{i}", mv=0, type_line="Basic Land — Forest", player=who)
    cast(eng, card(eng, "New Frontiers", zone=Zone.HAND), x=2)
    taken = {"p1": 0, "p2": 0}
    for _ in range(12):
        choice = eng.state.pending_choice
        if not choice:
            break
        opts = [o for o in choice["options"] if o["id"] != "decline"]
        if not opts:
            eng.resolve_pending_choice("decline")
            continue
        taken[choice["player_id"]] += 1
        eng.resolve_pending_choice(str(opts[0]["id"]))
    assert taken == {"p1": 2, "p2": 2}
    assert sum(1 for o in eng.state.battlefield if o.name.endswith(("Basic0", "Basic1", "Basic2"))) == 4


def test_borderland_explorer_searches_only_for_players_who_discarded():
    """The "each player who discarded a card this way" wrapper hands the iterated player to the search (RULE 608.2c)."""
    eng = game(library=0)
    _own_library(eng, "p1", "A")
    _own_library(eng, "p2", "B")
    filler(eng, "HandA", type_line="Creature", player="p1", zone=Zone.HAND)
    filler(eng, "HandB", type_line="Creature", player="p2", zone=Zone.HAND)
    put_on_battlefield(eng, "Borderland Explorer")
    searchers = []
    for _ in range(12):
        choice = eng.state.pending_choice
        if not choice:
            break
        if choice["kind"] == "search":
            searchers.append(choice["player_id"])
            eng.resolve_pending_choice(str(next(o["id"] for o in choice["options"] if o["id"] != "decline")))
            continue
        # the discard may: p1 accepts, p2 declines
        ids = [str(o["id"]) for o in choice["options"]]
        wants = choice["player_id"] == "p1"
        eng.resolve_pending_choice(next((i for i in ids if (i in ("do", "yes")) == wants), ids[0]))
    assert searchers == ["p1"]
    assert [o.name[0] for o in eng.state.player_by_id("p1").hand if o.name != "HandA"] == ["A"]


def test_path_to_exile_gives_the_exiled_creatures_controller_the_basic_land():
    """"Exile target creature. Its controller may search their library ..." (RULE 701.19a): the searcher is the
    creature's controller, not the caster, and only their own library is searched."""
    eng = game(library=0)
    _own_library(eng, "p1", "A")
    _own_library(eng, "p2", "B")
    victim = filler(eng, "Victim", type_line="Creature", player="p2", power=2, toughness=2)
    cast(eng, card(eng, "Path to Exile", zone=Zone.HAND), targets=[victim])
    assert _searcher(eng) == "p2"
    assert _offered(eng) == {"BPlains", "BSwamp"}
    _pick(eng, "BPlains")
    assert any(o.name == "BPlains" and o.tapped and o.controller_id == "p2" for o in eng.state.battlefield)
    assert victim.zone == Zone.EXILE

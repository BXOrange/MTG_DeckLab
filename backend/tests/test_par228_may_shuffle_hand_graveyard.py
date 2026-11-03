"""PAR-228 residue: "Each player may shuffle their hand and graveyard into their library. Each player who does
draws seven cards." (Step Between Worlds, Turtles in Time) -- a per-player choice, asked in turn order
(RULE 101.4), where only the players who shuffled draw (RULE 608.2c, 701.20)."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle

STEP = ("Each player may shuffle their hand and graveyard into their library. Each player who does draws seven "
        "cards. Exile Step Between Worlds.")
TURTLES = ("Return all creatures to their owners' hands. Each player may shuffle their hand and graveyard into "
           "their library, then each player who does draws seven cards.\nExile Turtles in Time.")
LIBRARY_SIZE = 10
DRAWN = 7


def _card(name, oracle, **kw):
    return Card(id=name, name=name, type_line="Sorcery", oracle_text=oracle, is_sorcery=True, **kw)


def _stock(eng, pid):
    """One marked card in hand and graveyard, a library to draw from."""
    player = eng.state.player_by_id(pid)
    for i in range(LIBRARY_SIZE):
        player.add_to_zone(GameObject(Card(id=f"{pid}L{i}", name=f"{pid}L{i}", type_line="Land", oracle_text=""),
                                      owner_id=pid, zone=Zone.LIBRARY), Zone.LIBRARY)
    held = GameObject(Card(id=f"{pid}H", name=f"{pid}H", type_line="Land", oracle_text=""),
                      owner_id=pid, zone=Zone.HAND)
    gone = GameObject(Card(id=f"{pid}G", name=f"{pid}G", type_line="Land", oracle_text=""),
                      owner_id=pid, zone=Zone.GRAVEYARD)
    player.add_to_zone(held, Zone.HAND)
    player.add_to_zone(gone, Zone.GRAVEYARD)
    return held, gone


def _cast(oracle, name):
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    marks = {pid: _stock(eng, pid) for pid in ("p1", "p2")}
    spell = GameObject(_card(name, oracle), owner_id="p1", zone=Zone.HAND)
    spell.controller_id = "p1"
    bind_from_catalogue(spell)
    eng.state.player_by_id("p1").add_to_zone(spell, Zone.HAND)
    eng.cast_spell(eng.state.player_by_id("p1"), spell)
    eng.resolve_until_stable()
    return eng, marks


def _answer(eng, expected_player, option):
    choice = eng.state.pending_choice
    assert choice is not None and choice["player_id"] == expected_player, choice
    eng.resolve_pending_choice(option)
    eng.resolve_until_stable()


@pytest.mark.parametrize("name,oracle", [("Step Between Worlds", STEP), ("Turtles in Time", TURTLES)])
def test_real_cards_modeled(name, oracle):
    assert parse_oracle(_card(name, oracle.replace("seven", "7"))).modeled


@pytest.mark.parametrize("clause", [
    "each player may shuffle their hand and graveyard into their library",
    "each player may shuffle their hand and graveyard into their library. each player draws 7 cards",
    "each player may shuffle your hand and graveyard into their library. each player who does draws 7 cards",
])
def test_adversarial_not_claimed(clause):
    assert match_clause(clause) is None


@pytest.mark.parametrize("name,oracle", [("Step Between Worlds", STEP), ("Turtles in Time", TURTLES)])
def test_decliner_neither_shuffles_nor_draws(name, oracle):
    eng, marks = _cast(oracle, name)
    _answer(eng, "p1", "yes")          # the active player is asked first (RULE 101.4)
    _answer(eng, "p2", "decline")
    p1, p2 = (eng.state.player_by_id(p) for p in ("p1", "p2"))
    assert len(p1.hand) == DRAWN and not p1.graveyard
    assert len(p1.library) == LIBRARY_SIZE + 2 - DRAWN  # hand + graveyard card joined the library
    assert p2.hand == [marks["p2"][0]] and p2.graveyard == [marks["p2"][1]]
    assert len(p2.library) == LIBRARY_SIZE
    assert eng.state.pending_choice is None


def test_both_decline_changes_nothing_and_both_accept_draws_both():
    eng, marks = _cast(STEP, "Step Between Worlds")
    _answer(eng, "p1", "decline")
    _answer(eng, "p2", "decline")
    for pid in ("p1", "p2"):
        player = eng.state.player_by_id(pid)
        assert player.hand == [marks[pid][0]] and player.graveyard == [marks[pid][1]]
    eng, _ = _cast(STEP, "Step Between Worlds")
    _answer(eng, "p1", "yes")
    _answer(eng, "p2", "yes")
    assert all(len(eng.state.player_by_id(p).hand) == DRAWN for p in ("p1", "p2"))


def test_empty_zones_still_count_as_shuffled_and_draw():
    """A player with an empty hand and graveyard still shuffled; "each player who does" draws."""
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    for pid in ("p1", "p2"):
        player = eng.state.player_by_id(pid)
        for i in range(LIBRARY_SIZE):
            player.add_to_zone(GameObject(Card(id=f"{pid}{i}", name=f"{pid}{i}", type_line="Land", oracle_text=""),
                                          owner_id=pid, zone=Zone.LIBRARY), Zone.LIBRARY)
    spell = GameObject(_card("Step Between Worlds", STEP), owner_id="p1", zone=Zone.HAND)
    spell.controller_id = "p1"
    bind_from_catalogue(spell)
    eng.state.player_by_id("p1").add_to_zone(spell, Zone.HAND)
    eng.cast_spell(eng.state.player_by_id("p1"), spell)
    eng.resolve_until_stable()
    _answer(eng, "p1", "yes")
    _answer(eng, "p2", "yes")
    assert all(len(eng.state.player_by_id(p).hand) == DRAWN for p in ("p1", "p2"))


def test_pending_choice_survives_clone_and_resumes_per_player():
    eng, marks = _cast(STEP, "Step Between Worlds")
    assert eng.state.pending_choice["player_id"] == "p1"
    twin = eng.state.clone()
    assert twin.pending_choice["player_id"] == "p1"
    _answer(eng, "p1", "yes")
    # Undo-style: the clone taken before p1 answered still holds p1's untouched zones and the same question.
    p1_twin = twin.player_by_id("p1")
    assert [o.name for o in p1_twin.hand] == ["p1H"] and [o.name for o in p1_twin.graveyard] == ["p1G"]
    assert eng.state.pending_choice["player_id"] == "p2"
    mid = eng.state.clone()                    # clone while p2's question is pending
    assert mid.pending_choice["player_id"] == "p2"
    _answer(eng, "p2", "decline")
    p2 = eng.state.player_by_id("p2")
    assert p2.hand == [marks["p2"][0]] and len(p2.hand) == 1

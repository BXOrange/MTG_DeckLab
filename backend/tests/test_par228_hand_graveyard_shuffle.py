"""PAR-228: "shuffle your hand and graveyard into your library" composition (RULE 701.20).

The mass "each player shuffles their ..." form and the controller's "you shuffle your ..." form share the engine's
`shuffle_hand_and_graveyard_into_library`; the optional ", then draws N cards" tail is a same-scope `draw` ordered
after it. Subject/pronoun mismatches and the per-player "may" form stay unclaimed.
"""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle

EACH = "each player shuffles their hand and graveyard into their library, then draws 7 cards"  # normalised clause: no period
SHUFFLE = {"type": "shuffle_hand_and_graveyard_into_library"}


def test_each_player_with_draw_tail_is_seq():
    (spec,) = match_clause(EACH)
    assert spec.type == "seq"
    assert spec.params["effects"] == [
        {**SHUFFLE, "params": {"scope": "each_player"}},
        {"type": "draw", "params": {"count": 7, "selector": "each_player"}},
    ]


def test_each_player_standalone_and_you_forms():
    (spec,) = match_clause("each player shuffles their hand and graveyard into their library")
    assert (spec.type, spec.params) == (SHUFFLE["type"], {"scope": "each_player"})
    (spec,) = match_clause("you shuffle your hand and graveyard into your library, then draw 7 cards")
    assert spec.params["effects"] == [
        {**SHUFFLE, "params": {}}, {"type": "draw", "params": {"count": 7}},
    ]


@pytest.mark.parametrize("clause", [
    "you shuffle their hand and graveyard into your library",
    "each player shuffles your hand and graveyard into their library",
    "each player may shuffle their hand and graveyard into their library",
    "target player shuffles their hand and graveyard into their library",
])
def test_adversarial_not_claimed(clause):
    assert match_clause(clause) is None


def _card(name, oracle, type_line="Sorcery"):
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle,
                is_sorcery=type_line == "Sorcery")


@pytest.mark.parametrize("name,oracle", [
    ("Echo of Eons", EACH.capitalize() + ".\nFlashback {2}{U}"),
    ("Time Reversal", EACH.capitalize() + ". Exile Time Reversal."),
])
def test_real_cards_modeled(name, oracle):
    assert parse_oracle(_card(name, oracle.replace("draws 7", "draws seven"))).modeled


def test_jace_ultimate_keeps_you_draw_scope():
    card = _card("Jace, the Living Guildpact", "−8: Each player shuffles their hand and graveyard into their library. "
                 "You draw seven cards.", "Legendary Planeswalker — Jace")
    res = parse_oracle(card)
    assert res.modeled
    effects = [e for a in res.specs for e in a.effects]
    assert [e.type for e in effects] == [SHUFFLE["type"], "draw"]
    assert "selector" not in effects[1].params


def test_execution_moves_zones_and_draws_per_player():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    eng.begin_turn()
    spell = GameObject(_card("Wheelish", EACH), owner_id="p1", zone=Zone.STACK)
    spell.controller_id = "p1"
    bind_from_catalogue(spell)
    marked = {}
    for pid in ("p1", "p2"):
        player = eng.state.player_by_id(pid)
        for i in range(10):
            lib = GameObject(Card(id=f"{pid}L{i}", name=f"{pid}L{i}", type_line="Land", oracle_text=""),
                             owner_id=pid, zone=Zone.LIBRARY)
            player.add_to_zone(lib, Zone.LIBRARY)
        gone = GameObject(Card(id=f"{pid}G", name=f"{pid}G", type_line="Land", oracle_text=""),
                          owner_id=pid, zone=Zone.GRAVEYARD)
        held = GameObject(Card(id=f"{pid}H", name=f"{pid}H", type_line="Land", oracle_text=""),
                          owner_id=pid, zone=Zone.HAND)
        player.add_to_zone(gone, Zone.GRAVEYARD)
        player.add_to_zone(held, Zone.HAND)
        marked[pid] = (gone, held)
    for effect in build_effects(match_clause(EACH), spell):
        effect.apply(GameContext(eng.state, eng.rules), None)
    for pid in ("p1", "p2"):
        player = eng.state.player_by_id(pid)
        assert len(player.hand) == 7
        assert not player.graveyard
        assert len(player.library) == 12 - 7

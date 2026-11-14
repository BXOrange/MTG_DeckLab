"""Chronomantic Escape: until your next turn creatures can't attack you; exiles itself with three time counters."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.star_trek import cast, game, stock_library, vanilla

NAME = "Chronomantic Escape"
ORACLE = (
    "Until your next turn, creatures can't attack you. Exile Chronomantic Escape with three time counters on it.\n"
    "Suspend 3—{2}{W} (Rather than cast this card from your hand, you may pay {2}{W} and exile it with three time "
    "counters on it. At the beginning of your upkeep, remove a time counter. When the last is removed, you may cast "
    "it without paying its mana cost.)"
)
TIME_COUNTERS = 3
WALK_LIMIT = 60  # bounded step walk between turns


def _escape():
    return Card(id="esc", name=NAME, type_line="Sorcery", is_sorcery=True, mana_cost_string="{4}{W}{W}",
                converted_mana_cost=6, oracle_text=ORACLE)


def _cast_escape(engine, p1):
    obj = GameObject(_escape(), owner_id="p1", zone=Zone.HAND)
    obj.controller_id = "p1"
    p1.add_to_zone(obj, Zone.HAND)
    bind_from_catalogue(obj)
    cast(engine, p1, obj)
    return obj


def _walk_to(engine, player_id, step):
    for _ in range(WALK_LIMIT):
        if engine.state.active_player.id == player_id and engine.state.current_step == step:
            return
        engine.advance_step()
        engine.resolve_until_stable()
    raise AssertionError(f"never reached {player_id}'s {step}")


def _board():
    engine, p1, p2 = game(via_steps=True)
    mine = vanilla(engine, "p1", "Mine")
    foe = vanilla(engine, "p2", "Foe")
    return engine, p1, p2, mine, foe


def test_specs_are_fresh_valid():
    first, second = specs_for(_escape()), specs_for(_escape())
    assert first[0] is not second[0] and [s.ability_kind for s in first][:1] == ["spell_effect"]
    for spec in first:
        spec.validate()


def test_it_exiles_itself_with_three_time_counters_instead_of_the_graveyard():
    engine, p1, p2, mine, foe = _board()
    obj = _cast_escape(engine, p1)
    assert obj.zone == Zone.EXILE and obj.counters.get("time") == TIME_COUNTERS and obj not in p1.graveyard


def _declare(engine, attacker, defender_player):
    """Declare ``attacker`` against ``defender_player`` in the declare-attackers step of its controller's turn."""
    owner = engine.state.player_by_id(attacker.controller_id)
    while engine.state.current_step != "declare_attackers":
        engine.advance_step()
        engine.resolve_until_stable()
    attacker.summoning_sick = False
    engine.declare_attackers(owner, [{"attacker": attacker, "defender": {"kind": "player", "id": defender_player.id,
                                                                         "label": defender_player.id}}])


def test_opponents_creatures_cannot_attack_you_during_their_turn():
    engine, p1, p2, mine, foe = _board()
    _cast_escape(engine, p1)
    _walk_to(engine, "p2", "main1")
    with pytest.raises(Exception):
        _declare(engine, foe, p1)
    assert not foe.attacking


def test_your_own_creatures_can_still_attack_while_it_lasts():
    engine, p1, p2, mine, foe = _board()
    _cast_escape(engine, p1)
    _declare(engine, mine, p2)
    assert mine.attacking


def test_the_bar_ends_when_your_next_turn_begins():
    engine, p1, p2, mine, foe = _board()
    stock_library(engine, "p2", 8)
    stock_library(engine, "p1", 8)
    _cast_escape(engine, p1)
    _walk_to(engine, "p1", "upkeep")  # your next turn begins: the effect ends
    _walk_to(engine, "p2", "main1")
    _declare(engine, foe, p1)
    assert foe.attacking

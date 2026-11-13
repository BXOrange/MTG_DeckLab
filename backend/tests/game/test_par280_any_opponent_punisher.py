"""PAR-280 (RULE 101.4, 608.2d): "Any opponent may have you <benefit>. If a player does / no player does, ..." --
Distant Memories and Sin Prodder -- parsed, then executed in a real three-player engine: each opponent in turn order
decides, the first to accept ends the sweep, and the accepting player is "that player" for Sin Prodder's damage."""

from __future__ import annotations

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.game import creature

_DB = CardDatabase(DB_PATH)
LIBRARY_SIZE = 12


def _named(name):
    card = _DB.get_card(name)
    assert card is not None, name
    return card


def _engine(p1_cards):
    eng = GameEngine.new_game([
        ("p1", "Alice", list(p1_cards)),
        ("p2", "Bob", [creature(f"B{i}") for i in range(LIBRARY_SIZE)]),
        ("p3", "Cara", [creature(f"C{i}") for i in range(LIBRARY_SIZE)]),
    ], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _answer(eng, option):
    choice = eng.state.pending_choice
    assert choice is not None
    eng.resolve_pending_choice(option)
    eng.resolve_until_stable()


def _asked(eng):
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "all_decline_or"
    return choice["player_id"]


def _cast_distant_memories():
    tutor_target = creature("Tutored Bear")
    eng = _engine([tutor_target] + [creature(f"A{i}") for i in range(LIBRARY_SIZE)])
    p1 = eng.state.player_by_id("p1")
    spell = GameObject(_named("Distant Memories"), owner_id="p1", zone=Zone.HAND)
    p1.hand.append(spell)
    bind_from_catalogue(spell)
    p1.mana_pool.add_many({"U": 2, "C": 2})
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()
    return eng, p1


def _pick_tutored_card(eng):
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] != "all_decline_or"
    pick = next(o["id"] for o in choice["options"] if o["id"] != "decline")
    eng.resolve_pending_choice(pick)
    eng.resolve_until_stable()


def test_both_cards_are_modeled():
    assert parse_oracle(_named("Distant Memories")).coverage == MODELED
    assert parse_oracle(_named("Sin Prodder")).coverage == MODELED


def test_distant_memories_goes_to_hand_when_the_second_opponent_accepts():
    eng, p1 = _cast_distant_memories()
    _pick_tutored_card(eng)
    exiled = list(p1.exile)
    assert len(exiled) == 1
    hand_before = len(p1.hand)
    assert _asked(eng) == "p2"
    _answer(eng, "decline")
    assert _asked(eng) == "p3"
    _answer(eng, "pay")
    assert eng.state.pending_choice is None
    assert exiled[0] in p1.hand and exiled[0] not in p1.exile
    assert len(p1.hand) == hand_before + 1  # only the exiled card, no draw


def test_distant_memories_draws_three_when_every_opponent_declines():
    eng, p1 = _cast_distant_memories()
    _pick_tutored_card(eng)
    before = len(p1.hand)
    exiled = list(p1.exile)
    assert _asked(eng) == "p2"
    _answer(eng, "decline")
    assert _asked(eng) == "p3"
    _answer(eng, "decline")
    assert len(p1.hand) == before + 3
    assert p1.exile == exiled  # the card stays exiled (ruling 2011-06-01)


def _sin_prodder_upkeep(top_card):
    eng = _engine([top_card] + [creature(f"A{i}") for i in range(LIBRARY_SIZE)])
    p1 = eng.state.player_by_id("p1")
    p1.library.append(p1.library.pop(0))  # the chosen card ends on top (index -1)
    top = p1.library[-1]
    prodder = GameObject(_named("Sin Prodder"), owner_id="p1", zone=Zone.BATTLEFIELD)
    prodder.controller_id = "p1"
    prodder.summoning_sick = False
    bind_from_catalogue(prodder)
    eng.state.add_to_battlefield(prodder)
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", player_id="p1", controller_id="p1"))
    eng.resolve_until_stable()
    return eng, p1, top


def test_sin_prodder_damages_the_accepting_opponent_by_the_cards_mana_value():
    eng, p1, top = _sin_prodder_upkeep(creature("Costly Bear", cost="{3}{G}"))
    assert top.name == "Costly Bear"
    assert _asked(eng) == "p2"
    _answer(eng, "decline")
    assert _asked(eng) == "p3"
    _answer(eng, "pay")
    assert top in p1.graveyard
    assert eng.state.player_by_id("p3").life == 20 - 4
    assert eng.state.player_by_id("p2").life == 20


def test_sin_prodder_puts_the_card_into_hand_when_nobody_accepts():
    eng, p1, top = _sin_prodder_upkeep(creature("Costly Bear", cost="{3}{G}"))
    _answer(eng, "decline")
    _answer(eng, "decline")
    assert top in p1.hand and top not in p1.graveyard
    assert eng.state.player_by_id("p2").life == 20 and eng.state.player_by_id("p3").life == 20

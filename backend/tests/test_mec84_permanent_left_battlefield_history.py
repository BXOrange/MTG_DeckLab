"""MEC-84 — controller-scoped permanent-left-battlefield history (Revolt).

`GameState.permanents_left_battlefield_this_turn` (+ the RULE 700.4 `creatures_`
sibling) count, per controller, how many permanents left the battlefield under
that player's control this turn — the history the "Revolt" / "Disappear"
ability words ("if a permanent left the battlefield under your control this
turn, …") gate on. Derived from the `LEAVES_BATTLEFIELD` events
the departure paths fire (ENG-47), so it needs no reset at `begin_turn`.

Reference: models/game/game_state.py (`remove_from_battlefield`),
game/engine/turn_loop_mixin.py (reset), game/static_conditions.py
(`permanent_left_battlefield_this_turn`), game/rules/casting_mixin.py
(`revolt_gate` entry counters), parser/oracle/catalogue/{static_handlers,
counters}.py.
"""

from __future__ import annotations

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.static_conditions import condition_holds
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _creature(state, name="Bear", controller="p1"):
    o = GameObject(
        Card(id=name[:6], name=name, type_line="Creature — Bear",
             is_creature=True, power=2, toughness=2),
        owner_id=controller, zone=Zone.BATTLEFIELD,
    )
    o.controller_id = controller
    state.add_to_battlefield(o)
    return o


def _artifact(state, name="Rock", controller="p1"):
    o = GameObject(Card(id=name[:6], name=name, type_line="Artifact"),
                   owner_id=controller, zone=Zone.BATTLEFIELD)
    o.controller_id = controller
    state.add_to_battlefield(o)
    return o


# --- tracker -----------------------------------------------------------


def test_leaving_the_battlefield_is_counted_per_controller():
    eng = _engine()
    a = _creature(eng.state, "A", "p1")
    b = _artifact(eng.state, "B", "p1")
    opp = _creature(eng.state, "Opp", "p2")

    eng.rules.exile(a)
    eng.rules.exile(b)
    eng.rules.exile(opp)

    assert eng.state.permanents_left_battlefield_this_turn == {"p1": 2, "p2": 1}
    # only the creature bumps the creature sibling
    assert eng.state.creatures_left_battlefield_this_turn == {"p1": 1, "p2": 1}


def test_condition_reads_the_controller_scoped_count():
    eng = _engine()
    cond_p = {"kind": "permanent_left_battlefield_this_turn"}
    cond_c = {"kind": "creature_left_battlefield_this_turn"}
    assert condition_holds(cond_p, eng.state, controller_id="p1") is False

    rock = _artifact(eng.state, "R", "p1")
    eng.rules.exile(rock)
    assert condition_holds(cond_p, eng.state, controller_id="p1") is True
    # a non-creature leaving does not satisfy the creature-narrowed sibling
    assert condition_holds(cond_c, eng.state, controller_id="p1") is False
    # nor does it help the opponent's Revolt
    assert condition_holds(cond_p, eng.state, controller_id="p2") is False


def test_begin_turn_clears_the_history():
    eng = _engine()
    eng.rules.exile(_creature(eng.state, "X", "p1"))
    assert eng.state.permanents_left_battlefield_this_turn
    eng.begin_turn()
    assert eng.state.permanents_left_battlefield_this_turn == {}
    assert eng.state.creatures_left_battlefield_this_turn == {}


def test_destruction_through_the_engine_registers():
    eng = _engine()
    tok = _creature(eng.state, "Token", "p1")
    eng.rules.destroy(tok)
    eng.rules.check_state_based_actions()
    assert tok not in eng.state.battlefield
    assert eng.state.permanents_left_battlefield_this_turn.get("p1", 0) == 1
    assert condition_holds(
        {"kind": "permanent_left_battlefield_this_turn"}, eng.state, controller_id="p1"
    )


# --- parser ----------------------------------------------------------


def test_real_revolt_cards_modeled():
    db = CardDatabase(DEFAULT_DB_PATH)
    for name in ("Silkweaver Elite", "Airdrop Aeronauts", "Countless Gears Renegade",
                 "Renegade Rallier", "Hidden Stockpile", "Solemn Recruit",
                 "Decommission", "Narnam Renegade", "Greenwheel Liberator",
                 "Night Market Aeronaut", "Putrid Pals"):
        c = db.get_card(name)
        assert c is not None, name
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- execute: entry-counter revolt gate ------------------------------


def test_greenwheel_liberator_gets_its_counters_only_after_a_revolt():
    db = CardDatabase(DEFAULT_DB_PATH)
    card = db.get_card("Greenwheel Liberator")
    assert card is not None

    # no permanent has left this turn → enters with no counters
    eng = _engine()
    obj = GameObject(card, owner_id="p1", zone=Zone.STACK)
    obj.controller_id = "p1"
    eng.rules._apply_entry_counters(obj)
    assert obj.plus_one_counters == 0

    # something left → enters with its two +1/+1 counters
    eng2 = _engine()
    eng2.rules.exile(_creature(eng2.state, "Fetched", "p1"))
    obj2 = GameObject(card, owner_id="p1", zone=Zone.STACK)
    obj2.controller_id = "p1"
    eng2.rules._apply_entry_counters(obj2)
    assert obj2.plus_one_counters == 2

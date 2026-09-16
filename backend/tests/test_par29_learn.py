"""PAR-29 — RULE 701.48 Learn (Strixhaven).

`RulesEngine.learn(player)` opens an optional "discard a card, then draw a
card" via the existing `_request_choose_objects` chooser (`optional=True` +
`then_specs`). **Documented simplification:** RULE 701.48a's "reveal a
Lesson card you own from outside the game" branch is dropped — this engine
has no sideboard / outside-the-game zone with a Commander-legal use (the
same call `card_registry/punishers.py` makes for Karn's -2).
`effects.LearnEffect` is a bare "you"-subject effect; the parser handler
`learn` matches the bare word.

Reference: game/rules/misc_mixin.py (`learn`), game/effects/core.py
(`LearnEffect`), parser/oracle/catalogue/handlers.py (`_learn`).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


# --- parse ---------------------------------------------------------------


def test_learn_clause_parses():
    assert match_clause("learn") == [EffectSpec("learn", {})]
    assert match_clause("learn a spell") is None


def test_real_learn_cards_modeled_end_to_end():
    spell = Card(id="CS", name="Cram Session", type_line="Instant",
                 is_instant=True, oracle_text="You gain 5 life.\nLearn.")
    assert parse_oracle(spell).modeled

    etb = Card(id="GP", name="Gnarled Professor", type_line="Creature — Elemental",
               is_creature=True, power=5, toughness=4,
               oracle_text="When this creature enters, learn.")
    assert parse_oracle(etb).modeled


# --- execute -----------------------------------------------------------------


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _fill(state, pid, hand=2, library=3):
    p = state.player_by_id(pid)
    for i in range(library):
        c = Card(id=f"{pid}L{i}", name=f"Lib{i}", type_line="Creature — Bear",
                 is_creature=True, power=1, toughness=1)
        p.add_to_zone(GameObject(c, owner_id=pid, zone=Zone.LIBRARY), Zone.LIBRARY)
    for i in range(hand):
        c = Card(id=f"{pid}H{i}", name=f"Hand{i}", type_line="Instant", is_instant=True)
        p.add_to_zone(GameObject(c, owner_id=pid, zone=Zone.HAND), Zone.HAND)
    return p


def test_learn_discard_then_draw():
    eng, state = _engine()
    p1 = _fill(state, "p1", hand=2, library=3)

    eng.rules.learn(p1)
    assert state.pending_choice["action"] == "discard"

    to_discard = p1.hand[0].instance_id
    eng.resolve_pending_choice(to_discard)

    assert len(p1.graveyard) == 1 and p1.graveyard[0].instance_id == to_discard
    assert len(p1.hand) == 2  # -1 discarded, +1 drawn
    assert len(p1.library) == 2  # drew one


def test_learn_decline_does_nothing():
    eng, state = _engine()
    p1 = _fill(state, "p1", hand=2, library=3)

    eng.rules.learn(p1)
    eng.resolve_pending_choice(None)  # decline the optional discard

    assert p1.graveyard == []
    assert len(p1.hand) == 2 and len(p1.library) == 3  # no discard, no draw


def test_learn_with_empty_hand_is_a_noop():
    eng, state = _engine()
    p1 = _fill(state, "p1", hand=0, library=3)

    eng.rules.learn(p1)

    assert state.pending_choice is None
    assert len(p1.library) == 3  # the Lesson branch is dropped — nothing happens


def test_learn_via_binder_on_etb():
    eng, state = _engine()
    p1 = _fill(state, "p1", hand=2, library=3)
    card = Card(id="PoS", name="Professor of Symbology",
                type_line="Creature — Human Cleric", is_creature=True,
                power=1, toughness=3,
                oracle_text="When this creature enters, learn.")
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id,
        controller_id="p1", object_types=sorted(obj.type_words),
    ))
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()

    assert state.pending_choice["action"] == "discard"
    eng.resolve_pending_choice(p1.hand[0].instance_id)
    assert len(p1.graveyard) == 1 and len(p1.hand) == 2

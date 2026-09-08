"""PAR-29 — "Blight N" (Bloomburrow): "put N -1/-1 counters on a creature
you control".

The negative sibling of Bolster: `RulesEngine.blight` (in
`mana_counters_mixin`) puts the counters on a creature the player picks (any
creature they control), opening a `blight` `pending_choice` when they
control 2+. `effects.BlightEffect` is a bare "you"-subject effect.

Only the standalone-verb form is modeled; the cost forms ("{cost}, Blight
N: <effect>") and the "you may blight N. If you do" wrapper stay UNMODELED.

Reference: game/rules/mana_counters_mixin.py (`blight`), game/effects/core.py
(`BlightEffect`), parser/oracle/catalogue/handlers.py.
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


def test_blight_parses_literal_only():
    assert match_clause("blight 1") == [EffectSpec("blight", {"amount": 1})]
    assert match_clause("blight 2") == [EffectSpec("blight", {"amount": 2})]
    assert match_clause("blight x") is None


def test_real_standalone_blight_card_modeled_end_to_end():
    urchin = Card(id="SU", name="Shadow Urchin", type_line="Creature — Ouphe",
                  is_creature=True, power=1, toughness=1,
                  oracle_text="Whenever this creature attacks, blight 1. "
                              "(Put a -1/-1 counter on a creature you control.)")
    assert parse_oracle(urchin).modeled


# --- execute -----------------------------------------------------------------


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state, eng.state.player_by_id("p1")


def _creature(name, owner="p1", tough=3):
    card = Card(id=name, name=name, type_line="Creature — Bear",
                is_creature=True, power=2, toughness=tough)
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    obj.summoning_sick = False
    return obj


def test_blight_with_no_creatures_does_nothing():
    eng, state, p1 = _engine()
    eng.rules.blight(p1, 2)
    assert state.pending_choice is None


def test_blight_single_creature_no_choice():
    eng, state, p1 = _engine()
    c = _creature("C")
    state.add_to_battlefield(c)

    eng.rules.blight(p1, 2)

    assert state.pending_choice is None
    assert c.counters.get("-1/-1", 0) == 2


def test_blight_multiple_creatures_opens_choice():
    eng, state, p1 = _engine()
    a, b = _creature("A"), _creature("B")
    state.add_to_battlefield(a)
    state.add_to_battlefield(b)

    eng.rules.blight(p1, 1)

    choice = state.pending_choice
    assert choice is not None and choice["kind"] == "blight"
    eng.resolve_pending_choice(str(b.instance_id))

    assert state.pending_choice is None
    assert b.counters.get("-1/-1", 0) == 1
    assert a.counters.get("-1/-1", 0) == 0


def test_blight_choice_defaults_to_first_on_missing_answer():
    eng, state, p1 = _engine()
    a, b = _creature("A"), _creature("B")
    state.add_to_battlefield(a)
    state.add_to_battlefield(b)

    eng.rules.blight(p1, 2)
    eng.resolve_pending_choice(None)

    assert state.pending_choice is None
    assert a.counters.get("-1/-1", 0) == 2


def test_blight_only_your_own_creatures():
    eng, state, p1 = _engine()
    mine = _creature("Mine", owner="p1")
    theirs = _creature("Theirs", owner="p2")
    state.add_to_battlefield(mine)
    state.add_to_battlefield(theirs)

    eng.rules.blight(p1, 1)

    assert state.pending_choice is None  # only one of *p1's* creatures
    assert mine.counters.get("-1/-1", 0) == 1
    assert theirs.counters.get("-1/-1", 0) == 0


def test_blight_lethal_counters_kill_via_sba():
    eng, state, p1 = _engine()
    c = _creature("C", tough=2)
    state.add_to_battlefield(c)

    eng.rules.blight(p1, 2)  # 2/2 → 0/0
    eng.recompute_continuous_effects()
    eng.rules.check_state_based_actions()

    assert c not in state.battlefield  # RULE 704.5f


def test_real_card_blights_on_attack_via_binder():
    eng, state, p1 = _engine()
    other = _creature("Other")
    state.add_to_battlefield(other)

    card = Card(id="SU", name="Shadow Urchin", type_line="Creature — Ouphe",
                is_creature=True, power=1, toughness=1,
                oracle_text="Whenever this creature attacks, blight 1.")
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    state.fire_event(GameEvent(
        EventType.ATTACKS, instance_id=obj.instance_id, controller_id="p1",
        object_types=sorted(obj.type_words),
    ))
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()

    # two eligible creatures (Shadow Urchin + Other) → a choice opened
    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "blight"

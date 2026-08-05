"""Closing the "Hobbits" saved deck's own commander, Frodo, Adventurous
Hobbit // Frodo, Sauron's Bane: "Whenever ~ attacks, if you gained 3 or more
life this turn, the Ring tempts you. Then if ~ is your Ring-bearer and the
Ring has tempted you two or more times this game, draw a card."

Three new small primitives, all in `effects.ConditionalEffect._condition_
holds`:

* `GameState.life_gained_this_turn` — a new per-turn tracker (RULE 119.3),
  mirroring the existing `cards_drawn_this_turn`'s "reset only the incoming
  active player" convention, since every card that reads it is a "whenever
  ~ attacks" trigger and a creature only ever attacks on its own
  controller's turn.
* `"is_ring_bearer"` — RULE 701.52a, "if ~ is/isn't your Ring-bearer".
  Also closes the "if you chose a creature other than ~ as your
  Ring-bearer" phrasing several *other* Ring cards use (Aragorn, Company
  Leader/Faramir, Field Commander/Galadriel of Lothlórien/Gandalf, Friend
  of the Shire) as `is_ring_bearer=False`.
* `"ring_tempted_at_least"` — RULE 701.51b, `Player.ring_level` threshold.

`_condition_holds` itself was generalized from an if/elif chain (exactly
one key ever set) to an AND-fold over every key present, since Frodo's own
second clause is the first card needing two conditions to hold together —
backward compatible, since every pre-existing condition dict still carries
exactly one key.

Reference: mtg_analyzer/{models/game_state,game/{effects,rules/{damage_
death_mixin,engine/turn_loop_mixin},parser/oracle/segmenter}}.py.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _frodo_card():
    return Card(
        id="Test Frodo", name="Test Frodo", type_line="Legendary Creature — Hobbit",
        is_creature=True, power=1, toughness=1, keywords=["Vigilance"],
        oracle_text=(
            "Vigilance\n"
            "Whenever this creature attacks, if you gained 3 or more life this "
            "turn, the Ring tempts you. Then if this creature is your Ring-bearer "
            "and the Ring has tempted you two or more times this game, draw a card."
        ),
    )


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _fire_attacks(state, obj, controller="p1"):
    state.fire_event(
        GameEvent(
            EventType.ATTACKS, attacker=obj.name, player_id=controller,
            instance_id=obj.instance_id, object_types=sorted(obj.type_words),
        )
    )


def test_frodo_full_card_is_modeled():
    assert parse_oracle(_frodo_card()).modeled


def test_life_gained_this_turn_resets_on_the_new_active_players_turn():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    eng.rules.gain_life(p1, 5)
    assert state.life_gained_this_turn["p1"] == 5

    eng.begin_turn()
    assert state.life_gained_this_turn["p1"] == 0


def test_first_clause_only_tempts_the_ring_when_life_was_gained():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    frodo = _bf(state, _frodo_card())

    # No life gained this turn -> the first "if" fails, no temptation.
    _fire_attacks(state, frodo)
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()
    assert p1.ring_level == 0

    # Gain 3+ life, attack again -> the Ring tempts you (and Frodo, as the
    # only creature, becomes the Ring-bearer outright).
    eng.rules.gain_life(p1, 3)
    _fire_attacks(state, frodo)
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()
    assert p1.ring_level == 1
    assert p1.ring_bearer_id == frodo.instance_id


def test_second_clause_needs_both_ring_bearer_and_tempted_twice():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    frodo = _bf(state, _frodo_card())
    p1.library.append(GameObject(Card(id="Topdeck", name="Topdeck", type_line="Land"),
                                  owner_id="p1", zone=Zone.LIBRARY))
    before = len(p1.hand)

    # First temptation: ring_level -> 1, not >= 2 yet, so no draw even
    # though Frodo is the (only) Ring-bearer.
    eng.rules.gain_life(p1, 3)
    _fire_attacks(state, frodo)
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    assert p1.ring_level == 1
    assert len(p1.hand) == before  # no draw yet

    # Second temptation: ring_level -> 2, Frodo is still the bearer -> draw.
    eng.begin_turn()
    eng.rules.gain_life(p1, 3)
    _fire_attacks(state, frodo)
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    assert p1.ring_level == 2
    assert len(p1.hand) == before + 1

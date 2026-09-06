"""RULE 701.51a's "The Ring tempts you" keyword action (Tales of
Middle-earth) — closing the deck-first audit of the "Hobbits" saved deck's
own set-specific mechanic (PARSER_LONG_TAIL.md's set-specific-mechanics
track).

Two pieces:

* **"The Ring tempts you." as a resolve-time effect.** The engine
  primitive (`RulesEngine.the_ring_tempts_you`) and the `EffectSpec` type
  (`"the_ring_tempts_you"`, `effects.TheRingTemptsYouEffect`) already
  existed — built for one hand-authored card — so this is purely the
  general oracle-text recognition (`catalogue.handlers._ring_tempts_you`).
* **"Whenever the Ring tempts you, `<effect>`." as a trigger condition.**
  Genuinely new: `RulesEngine.the_ring_tempts_you` fired no event at all
  before this, so no card using this template could ever have been
  modeled regardless of what else was fixed. New `EventType.RING_TEMPTED`,
  fired once the Ring-bearer choice is settled (immediately for the
  0/1-candidate paths, deferred to `resolve_ring_bearer_choice` for the
  interactive 2+-candidate path, so a trigger reading "if you chose a
  creature other than ~" always sees the final bearer).

Also covers "burden" joining `_NAMED_COUNTER_KINDS` (The One Ring's own
"{T}: Put a burden counter on ~...").

Reference: mtg_analyzer/{models/events,game/rules/misc_mixin,game/
effect_binder,parser/oracle/{segmenter,catalogue/handlers}}.py.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _creature(name="Grizzly Bears", power=2, toughness=2):
    return Card(id=name, name=name, type_line="Creature — Bear",
                is_creature=True, power=power, toughness=toughness)


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


# ---------------------------------------------------------------------------
# "The Ring tempts you." — the effect
# ---------------------------------------------------------------------------


def test_ring_tempts_you_parses():
    assert match_clause("the ring tempts you") == [EffectSpec("the_ring_tempts_you", {})]


def test_nazgul_first_line_is_claimed():
    card = Card(
        id="Test Nazgul", name="Test Nazgul", type_line="Creature — Wraith",
        is_creature=True, power=2, toughness=2, keywords=["Deathtouch"],
        oracle_text="Deathtouch\nWhen this creature enters, the Ring tempts you.",
    )
    result = parse_oracle(card)
    assert result.modeled


def test_ring_tempts_you_executes_and_levels_the_emblem():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    _bf(state, _creature("Bearer"))
    assert getattr(p1, "ring_level", 0) == 0

    eng.rules.the_ring_tempts_you(p1)

    assert p1.ring_level == 1
    assert p1.ring_bearer_id is not None


def test_ring_bearer_draws_and_discards_after_second_temptation_and_attack():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    bearer = _bf(state, _creature("Bearer"))
    p1.library.append(GameObject(_creature("Topdeck"), owner_id="p1", zone=Zone.LIBRARY))
    p1.hand.append(GameObject(_creature("Discard Me"), owner_id="p1", zone=Zone.HAND))

    eng.rules.the_ring_tempts_you(p1)
    state.fire_event(GameEvent(EventType.ATTACKS, player_id="p1", instance_id=bearer.instance_id))
    eng.resolve_until_stable()
    assert len(p1.hand) == 1  # Ring level 1 has no draw/discard ability yet.

    eng.rules.the_ring_tempts_you(p1)
    state.fire_event(GameEvent(EventType.ATTACKS, player_id="p1", instance_id=bearer.instance_id))
    eng.resolve_until_stable()
    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "choose_objects"
    eng.rules.resolve_choose_objects_choice(p1.hand[0].instance_id)
    eng.resolve_until_stable()

    assert p1.ring_level == 2
    assert len(p1.hand) == 1  # one card drawn, then one card discarded
    assert any(card.name == "Topdeck" for card in p1.hand)


# ---------------------------------------------------------------------------
# "Whenever the Ring tempts you, <effect>." — the trigger condition
# ---------------------------------------------------------------------------


def test_ring_tempted_trigger_full_card_is_modeled():
    card = Card(
        id="Test Nazgul 2", name="Test Nazgul 2", type_line="Creature — Wraith",
        is_creature=True, power=2, toughness=2,
        oracle_text="Whenever the Ring tempts you, draw a card.",
    )
    result = parse_oracle(card)
    assert result.modeled
    spec = result.effect_specs[0]
    assert spec.trigger == {"event": "RING_TEMPTED", "condition": {"subject": "you"}}


def test_ring_tempted_trigger_fires_with_a_single_creature_candidate():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    payoff_card = Card(
        id="Test Payoff", name="Test Payoff", type_line="Creature — Human",
        is_creature=True, power=1, toughness=1,
        oracle_text="Whenever the Ring tempts you, draw a card.",
    )
    _bf(state, payoff_card)
    p1.library.append(GameObject(_creature("Topdeck"), owner_id="p1", zone=Zone.LIBRARY))
    before = len(p1.hand)

    eng.rules.the_ring_tempts_you(p1)  # single creature on board -> no interactive choice
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()

    assert len(p1.hand) == before + 1


def test_ring_tempted_trigger_waits_for_the_interactive_bearer_choice():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    payoff_card = Card(
        id="Test Payoff 2", name="Test Payoff 2", type_line="Creature — Human",
        is_creature=True, power=1, toughness=1,
        oracle_text="Whenever the Ring tempts you, draw a card.",
    )
    payoff = _bf(state, payoff_card)
    other = _bf(state, _creature("Second Candidate"))
    p1.library.append(GameObject(_creature("Topdeck"), owner_id="p1", zone=Zone.LIBRARY))
    before = len(p1.hand)

    eng.rules.the_ring_tempts_you(p1)  # 2 candidates -> opens a ring_bearer choice
    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "ring_bearer"
    # No RING_TEMPTED event yet — the trigger must not fire before the
    # bearer is actually settled.
    assert eng.rules.put_triggers_on_stack() == 0

    eng.rules.resolve_ring_bearer_choice(other.instance_id)
    assert p1.ring_bearer_id == other.instance_id
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()

    assert len(p1.hand) == before + 1
    assert payoff in state.battlefield  # unaffected either way


# ---------------------------------------------------------------------------
# "burden" counters (The One Ring)
# ---------------------------------------------------------------------------


def test_put_a_burden_counter_on_self_parses():
    assert match_clause("put a burden counter on ~") == [
        EffectSpec("add_counters", {"count": 1, "kind": "burden"})
    ]


def test_the_one_ring_burden_clause_is_claimed():
    card = Card(
        id="Test One Ring", name="Test One Ring", type_line="Legendary Artifact",
        oracle_text="{T}: Put a burden counter on this artifact, then draw a card.",
    )
    result = parse_oracle(card)
    assert result.modeled

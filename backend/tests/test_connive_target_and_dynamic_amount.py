"""PAR-29 "Parser-shaped only" residue — the widened `ConniveEffect` (RULE
701.47/701.50): a `TargetSpec`/previous-subject subject alongside the
original bare-self one, and RULE 701.50d's dynamic "connives X" (a live
count-selector or a firing trigger's own event field), replacing the
original fixed-N=1-only implementation. Parse-level coverage of the new
oracle-text rows is in `test_par21_keyword_actions.py`; this file is the
execute-level half (per the extend-parser skill's own lesson: a parse-only
test has twice shipped a family that crashed on first real use).

RULE 701.50d: "connives N" draws N cards, discards N cards — one N-card
choice, not N separate 1-and-1 cycles — then places a counter for each
nonland card among those N discards.
"""

from __future__ import annotations

from mtg_analyzer.game.effects.core import ConniveEffect, GameContext
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player


def _land(name):
    return Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)


def _nonland(name):
    return Card(id=name, name=name, type_line="Instant", is_instant=True)


def _rules():
    p1 = Player(id="p1", life=20)
    p2 = Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    engine = RulesEngine(state)
    return engine, state, p1, p2


def _lib_card(player, card):
    obj = GameObject(card, owner_id=player.id, zone=Zone.LIBRARY)
    player.library.append(obj)  # append = bottom; last appended is drawn first
    return obj


def test_target_kind_connives_the_targeted_creatures_own_controller():
    # RULE 701.47: the *conniving permanent's* controller draws/discards —
    # not necessarily this effect's own controller. A target on an
    # opponent's creature must still have that opponent draw/discard.
    engine, state, p1, p2 = _rules()
    _lib_card(p2, _nonland("Bolt"))
    target = GameObject(
        Card(id="Bear", name="Bear", type_line="Creature — Bear",
             is_creature=True, power=2, toughness=2),
        owner_id="p2", zone=Zone.BATTLEFIELD,
    )
    state.add_to_battlefield(target)

    ctx = GameContext(state, engine)
    ConniveEffect(target_kind="creature_you_dont_control").apply(ctx, targets=[target])

    assert not p2.library  # p2 (the target's controller) drew, not p1
    assert target.counters.get("+1/+1", 0) == 1


def test_dynamic_x_draws_and_discards_x_cards_and_counts_every_nonland():
    engine, state, p1, _ = _rules()
    _lib_card(p1, _land("Forest"))
    _lib_card(p1, _nonland("Shock"))
    _lib_card(p1, _nonland("Bolt"))  # top: drawn first

    source = GameObject(
        Card(id="Conniver", name="Conniver", type_line="Creature — Rogue",
             is_creature=True, power=1, toughness=1),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    state.add_to_battlefield(source)

    ctx = GameContext(state, engine)
    ConniveEffect(source=source, times=3).apply(ctx)

    assert not p1.library  # all 3 drawn
    assert not p1.hand  # forced discard: hand size == count, no real choice
    assert len(p1.graveyard) == 3
    assert source.counters.get("+1/+1", 0) == 2  # Shock + Bolt, not Forest


def test_connive_zero_is_a_no_op_rule_701_50e():
    engine, state, p1, _ = _rules()
    _lib_card(p1, _nonland("Bolt"))
    source = GameObject(
        Card(id="Conniver", name="Conniver", type_line="Creature — Rogue",
             is_creature=True, power=1, toughness=1),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    state.add_to_battlefield(source)

    ctx = GameContext(state, engine)
    ConniveEffect(source=source, times_from_count_selector="attacking_creatures").apply(ctx)

    assert len(p1.library) == 1  # nothing drawn
    assert source.counters.get("+1/+1", 0) == 0


def test_times_from_trigger_event_reads_the_firing_events_own_field():
    # Mask of the Schemer: "…it connives X, where X is the amount of damage
    # it dealt to that player."
    engine, state, p1, _ = _rules()
    for name in ("Bolt", "Shock"):
        _lib_card(p1, _nonland(name))
    source = GameObject(
        Card(id="Masked", name="Masked", type_line="Creature — Rogue",
             is_creature=True, power=2, toughness=2),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    state.add_to_battlefield(source)

    ctx = GameContext(state, engine)
    ctx.trigger_event = {"amount": 2}
    ConniveEffect(source=source, times_from_trigger_event="amount").apply(ctx)

    assert not p1.library
    assert source.counters.get("+1/+1", 0) == 2


def test_multiple_subjects_sequence_one_at_a_time_via_deferred_effects():
    # "Each of X target creatures you control connive." (Change of Plans) —
    # two subjects sharing one controller. Looping both synchronously would
    # silently overwrite the first creature's still-unanswered discard
    # prompt with the second's own connive (the same failure mode the
    # SacrificeEffect `each_player`/`each_opponent` fix addressed) — instead
    # each subject's draw only happens once the *previous* one's discard
    # choice has actually been answered, via `GameState.deferred_effects`.
    # Every card is a nonland so which one gets picked doesn't matter to the
    # counter count, only the sequencing does.
    engine, state, p1, _ = _rules()
    _lib_card(p1, _nonland("Lib1"))
    _lib_card(p1, _nonland("Lib2"))  # top: drawn first
    p1.hand.append(GameObject(_nonland("Pre"), owner_id="p1", zone=Zone.HAND))
    creature_a = GameObject(
        Card(id="CreatureA", name="CreatureA", type_line="Creature — Rogue",
             is_creature=True, power=1, toughness=1),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    creature_b = GameObject(
        Card(id="CreatureB", name="CreatureB", type_line="Creature — Rogue",
             is_creature=True, power=1, toughness=1),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    state.add_to_battlefield(creature_a)
    state.add_to_battlefield(creature_b)

    ctx = GameContext(state, engine)
    ConniveEffect(
        target_kind="creature_you_control", count_selector="source_x_paid",
    ).apply(ctx, targets=[creature_a, creature_b])

    # Creature A drew "Lib2" onto a hand of 2 (Pre + Lib2) and must choose 1
    # of the 2 to discard — a real choice, so the rest is parked and
    # creature B hasn't connived (or even drawn) yet.
    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "choose_objects"
    assert creature_a.counters.get("+1/+1", 0) == 0
    assert creature_b.counters.get("+1/+1", 0) == 0
    assert len(p1.library) == 1  # only creature A's draw happened so far
    assert len(state.deferred_effects) == 1

    picked = state.pending_choice["options"][0]["instance_id"]
    engine.resolve_choice(picked)
    assert state.pending_choice is None
    assert creature_a.counters.get("+1/+1", 0) == 1
    # Resuming a `choose_objects` choice alone doesn't drain
    # `deferred_effects` — that's `GameEngine.resolve_until_stable`'s job
    # (`RulesEngine.resume_deferred_effects`); this test stays at the
    # `RulesEngine` level, so it drives the resume directly.
    assert engine.resume_deferred_effects() is True

    # Creature B now connives in turn: drew "Lib1" onto the one leftover
    # hand card from A's own discard — hand size 2 again, so this too opens
    # a real choice rather than silently resolving.
    assert not p1.library
    assert state.pending_choice is not None
    picked2 = state.pending_choice["options"][0]["instance_id"]
    engine.resolve_choice(picked2)
    assert state.pending_choice is None
    assert creature_b.counters.get("+1/+1", 0) == 1
    assert len(p1.hand) == 1  # one card never got discarded, and that's correct

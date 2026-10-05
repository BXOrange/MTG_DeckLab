"""ENG-47 — turn-stamped events and one "did X happen this turn" query.

Every fired event carries the turn it fired in; `GameState.events_this_turn` walks
the log back to the first earlier turn; and the `event_this_turn` condition asks a
trigger-shaped dict (the head of a trigger, in the past tense) over that window with
the binder's own predicate. So "a creature you controlled died this turn" is not a
tracker of its own — it is "whenever a creature you control dies", asked over the log.

Parse tests pin `catalogue/history_phrase.py` (and that it fails closed); engine tests
pin the stamp and the query; execute tests make the thing happen for real and watch a
gated effect switch on.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import static_conditions
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.history_phrase import parse_history_condition

from tests.test_par119_cast_trigger_grammar import _engine
from tests.test_par119_object_trigger_head import _fire_enter, _named
from tests.test_par120_count_phrase import _creature, _life_change, _put

# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------

DIES_YOU = {"event": "DIES", "condition": {"subject": "group", "controller": "you",
                                            "other": False, "filter": {"card_type": "creature"}}}


@pytest.mark.parametrize(
    "text, expected",
    [
        ("a creature you controlled died this turn",
         {"kind": "event_this_turn", "min": 1, "trigger": DIES_YOU}),
        ("a creature died under your control this turn",
         {"kind": "event_this_turn", "min": 1, "trigger": DIES_YOU}),
        ("three or more creatures died this turn",
         {"kind": "event_this_turn", "min": 3,
          "trigger": {"event": "DIES", "condition": {"subject": "group", "controller": "any",
                                                      "other": False, "filter": {"card_type": "creature"}}}}),
        ("no creatures died this turn",
         {"kind": "event_this_turn", "max": 0,
          "trigger": {"event": "DIES", "condition": {"subject": "group", "controller": "any",
                                                      "other": False, "filter": {"card_type": "creature"}}}}),
        ("two or more nonland permanents entered the battlefield under your control this turn",
         {"kind": "event_this_turn", "min": 2,
          "trigger": {"event": "ENTERS_BATTLEFIELD",
                      "condition": {"subject": "group", "controller": "you", "other": False,
                                    "filter": {"without_card_type": "land"}}}}),
        ("you gained life this turn",
         {"kind": "event_this_turn", "min": 1,
          "trigger": {"event": "LIFE_GAINED", "condition": {"subject": "you"}}}),
        ("you gained or lost life this turn",
         {"kind": "event_this_turn", "min": 1,
          "trigger": {"event": ["LIFE_GAINED", "LIFE_LOST"], "condition": {"subject": "you"}}}),
        ("you haven't cast a spell from your hand this turn",
         {"kind": "event_this_turn", "max": 0,
          "trigger": {"event": "SPELL_CAST", "condition": {"subject": "you"},
                      "spell_cast_from": ["hand"]}}),
        ("you've cast two or more noncreature spells this turn",
         {"kind": "event_this_turn", "min": 2,
          "trigger": {"event": "SPELL_CAST", "condition": {"subject": "you"},
                      "spell_filter": {"without_card_type": "creature"}}}),
        ("you sacrificed three or more clues this turn",
         {"kind": "event_this_turn", "min": 3,
          "trigger": {"event": "SACRIFICE", "condition": {"subject": "group", "controller": "you",
                                                           "other": False,
                                                           "filter": {"subtype": "clue"}}}}),
        ("you didn't attack with a creature this turn",
         {"kind": "event_this_turn", "max": 0,
          "trigger": {"event": "ATTACKS", "condition": {"subject": "group", "controller": "you",
                                                         "other": False,
                                                         "filter": {"card_type": "creature"}}}}),
        ("you didn't play a land this turn",
         {"kind": "event_this_turn", "max": 0,
          "trigger": {"event": "LAND_PLAYED", "condition": {"subject": "you"}}}),
    ],
)
def test_history_condition_parses(text, expected):
    assert parse_history_condition(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "a creature died",                          # not a turn-scoped phrase
        "frobnicators died this turn",              # an unknown word
        "you frobnicated this turn",
        "a creature died under a dragon's control this turn",
        "you cast a frobnicator this turn",
        "you drew two or more cards this turn",     # no per-card draw event to count yet
    ],
)
def test_history_condition_fails_closed(text):
    assert parse_history_condition(text) is None


@pytest.mark.parametrize(
    "name",
    [
        "Canyon Crab", "Denethor, Ruling Steward", "Grand Ball Guest", "Stoic Sphinx",
        "Inga Rune-Eyes", "Mercadian Atlas", "Titan Hunter", "Count Nefaria", "Loan Shark",
    ],
)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


# ---------------------------------------------------------------------------
# Engine: the stamp and the query
# ---------------------------------------------------------------------------


def test_every_fired_event_is_stamped_with_its_turn():
    engine, state = _engine()
    event = GameEvent(EventType.LIFE_GAINED, player_id="p1", amount=1)
    assert event.turn is None
    state.fire_event(event)
    assert event.turn == state.internal_turn.number


def test_events_this_turn_stops_at_the_first_earlier_turn():
    engine, state = _engine()
    state.fire_event(GameEvent(EventType.LIFE_GAINED, player_id="p1", amount=1))
    state.internal_turn.number += 1
    fresh = GameEvent(EventType.LIFE_LOST, player_id="p2", amount=2)
    state.fire_event(fresh)
    assert list(state.events_this_turn()) == [fresh]
    state.internal_turn.number += 1
    assert list(state.events_this_turn()) == []


def test_a_clone_keeps_this_turns_events_and_only_those():
    # undo restores a clone: "you gained life this turn" must survive it
    engine, state = _engine()
    state.fire_event(GameEvent(EventType.LIFE_GAINED, player_id="p1", amount=1))
    state.internal_turn.number += 1
    state.fire_event(GameEvent(EventType.LIFE_LOST, player_id="p1", amount=2))
    restored = state.clone()
    assert [e.type for e in restored.events_this_turn()] == [EventType.LIFE_LOST]
    assert len(restored.event_log) == 1
    assert len(state.event_log) == 2  # the live game's own log is untouched


def test_a_replacement_copy_is_stamped_when_it_fires_not_when_it_is_copied():
    original = GameEvent(EventType.DAMAGE, amount=3)
    original.turn = 5
    assert original.copy_with(amount=1).turn is None


# ---------------------------------------------------------------------------
# Execution: a condition flips when the thing really happens
# ---------------------------------------------------------------------------


def test_a_creature_you_controlled_dying_switches_the_gate_on_for_the_turn():
    engine, state = _engine()
    state.current_step = "main1"
    source = _put(state, "When ~ enters, if a creature you controlled died this turn, you gain 3 life.")
    victim = _creature(state, "Victim")
    theirs = _creature(state, "Theirs", owner="p2")
    assert _life_change(engine, state, lambda: _fire_enter(engine, state, source)) == 0
    engine.rules.destroy(theirs)
    engine.resolve_until_stable()
    assert _life_change(engine, state, lambda: _fire_enter(engine, state, source)) == 0   # not yours
    engine.rules.destroy(victim)
    engine.resolve_until_stable()
    assert _life_change(engine, state, lambda: _fire_enter(engine, state, source)) == 3
    state.internal_turn.number += 1
    assert _life_change(engine, state, lambda: _fire_enter(engine, state, source)) == 0   # a new turn


def test_a_count_of_events_uses_the_quantity():
    engine, state = _engine()
    state.current_step = "main1"
    source = _put(state, "When ~ enters, if two or more creatures died this turn, you gain 2 life.")
    first, second = _creature(state, "A"), _creature(state, "B", owner="p2")
    engine.rules.destroy(first)
    engine.resolve_until_stable()
    assert _life_change(engine, state, lambda: _fire_enter(engine, state, source)) == 0
    engine.rules.destroy(second)
    engine.resolve_until_stable()
    assert _life_change(engine, state, lambda: _fire_enter(engine, state, source)) == 2


def test_a_negative_history_gate_holds_until_the_thing_happens():
    engine, state = _engine()
    state.current_step = "main1"
    source = _put(state, "When ~ enters, if you didn't play a land this turn, you gain 2 life.")
    assert _life_change(engine, state, lambda: _fire_enter(engine, state, source)) == 2
    state.fire_event(GameEvent(EventType.LAND_PLAYED, player_id="p1"))
    assert _life_change(engine, state, lambda: _fire_enter(engine, state, source)) == 0


def test_you_gained_life_this_turn_reads_the_life_gained_events():
    engine, state = _engine()
    state.current_step = "main1"
    source = _put(state, "When ~ enters, if you gained life this turn, draw a card.")
    p1 = state.player_by_id("p1")
    p1.library.append(GameObject(Card(id="L", name="L", type_line="Land"), owner_id="p1", zone=Zone.LIBRARY))
    hand = len(p1.hand)
    _fire_enter(engine, state, source)
    assert len(p1.hand) == hand
    engine.rules.gain_life(p1, 2)
    _fire_enter(engine, state, source)
    assert len(p1.hand) == hand + 1


def test_a_static_gate_follows_the_turn_history_live():
    # "This creature has flying as long as you've cast a noncreature spell this turn."
    engine, state = _engine()
    state.current_step = "main1"
    source = _put(state, "This creature has flying as long as you've cast a noncreature spell this turn.")
    engine.recompute_continuous_effects()
    assert "flying" not in {k.lower() for k in source.granted_keywords}
    state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p1", instance_id=999,
                               object_types=["instant"]))
    engine.recompute_continuous_effects()
    # the spell object is unknown to the state, so the filter fails closed: still off
    assert "flying" not in {k.lower() for k in source.granted_keywords}
    spell = GameObject(Card(id="S", name="S", type_line="Instant", is_instant=True),
                       owner_id="p1", zone=Zone.HAND)
    state.player_by_id("p1").hand.append(spell)
    state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p1", instance_id=spell.instance_id,
                               object_types=["instant"]))
    engine.recompute_continuous_effects()
    assert "flying" in {k.lower() for k in source.granted_keywords}


def test_the_condition_is_relative_to_who_is_asking():
    engine, state = _engine()
    cond = static_conditions_cond = {
        "kind": "event_this_turn", "min": 1,
        "trigger": {"event": "LIFE_GAINED", "condition": {"subject": "you"}},
    }
    state.fire_event(GameEvent(EventType.LIFE_GAINED, player_id="p1", amount=1))
    assert static_conditions.condition_holds(cond, state, None, "p1") is True
    assert static_conditions.condition_holds(static_conditions_cond, state, None, "p2") is False


# ---------------------------------------------------------------------------
# The per-turn counters are derived from the log, not kept beside it
# ---------------------------------------------------------------------------


def _real_engine():
    from mtg_analyzer.game.game_engine import GameEngine

    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0)
    for pid in ("p1", "p2"):
        p = eng.state.player_by_id(pid)
        for i in range(6):
            p.library.append(GameObject(Card(id=f"{pid}{i}", name=f"{pid}{i}", type_line="Land"),
                                        owner_id=pid, zone=Zone.LIBRARY))
    eng.begin_turn()
    return eng, eng.state


def test_life_draw_and_discard_are_tallied_from_the_real_events():
    eng, state = _real_engine()
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    eng.rules.gain_life(p1, 4)
    eng.rules.lose_life(p2, 3)
    eng.rules.draw(p1, 2)
    eng.rules.discard(p1, 1)
    assert state.life_gained_this_turn["p1"] == 4 and state.life_gained_this_turn["p2"] == 0
    assert state.life_lost_this_turn["p2"] == 3
    assert state.cards_drawn_this_turn["p1"] == 2
    assert len(state.cards_drawn_this_turn_ids["p1"]) == 2
    assert state.cards_discarded_this_turn["p1"] == 1


def test_every_counter_moves_to_a_new_window_for_every_player_at_once():
    # Several of these used to reset only for the incoming active player, so an opponent's
    # total from *their* last turn was still readable during yours.
    eng, state = _real_engine()
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    eng.rules.gain_life(p2, 5)
    eng.rules.draw(p2, 1)
    assert state.life_gained_this_turn["p2"] == 5 and state.cards_drawn_this_turn["p2"] == 1
    eng.begin_turn()   # the other player's turn
    eng.begin_turn()   # and back
    assert state.life_gained_this_turn["p2"] == 0
    assert state.cards_drawn_this_turn["p2"] == 0


def test_a_cast_spell_carries_what_the_history_reads():
    eng, state = _real_engine()
    p1 = state.player_by_id("p1")
    card = Card(id="Wyrm", name="Wyrm", type_line="Creature — Dragon", is_creature=True,
                mana_cost_string="{X}{R}", color_identity={"R"}, power=1, toughness=1)
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    spell.controller_id = "p1"
    p1.hand.append(spell)
    eng.rules.cast_without_paying(p1, spell)
    assert state.spells_cast_this_turn["p1"] == 1
    assert state.noncreature_spells_cast_this_turn["p1"] == 0
    assert state.nonartifact_spells_cast_this_turn["p1"] == 1
    assert "dragon" in state.creature_type_spells_cast_this_turn["p1"]
    assert state.cast_x_spell_this_turn == {"p1"}
    assert state.spell_type_cast_counts_this_turn["p1"].get("creature") == 1


def test_damage_history_reads_the_damage_events():
    eng, state = _real_engine()
    hitter = _creature(state, "Hitter")
    victim = _creature(state, "Victim", owner="p2")
    p2 = state.player_by_id("p2")
    eng.rules.deal_damage(p2, 3, source=hitter, combat=True)
    eng.rules.deal_damage(victim, 2, source=hitter)
    assert state.damage_dealt_to_players_this_turn["p2"] == 3
    assert state.damage_dealt_by_this_turn["p1"] == 3
    assert state.combat_damage_to_players_this_turn[hitter.instance_id] == {"p2"}
    assert state.creatures_damaged_by_source_this_turn[victim.instance_id] == {hitter.instance_id}
    assert state.noncombat_damage_to_opponents_this_turn == {}
    eng.rules.deal_damage(p2, 2, source=hitter)
    assert state.noncombat_damage_to_opponents_this_turn["p1"] == 2

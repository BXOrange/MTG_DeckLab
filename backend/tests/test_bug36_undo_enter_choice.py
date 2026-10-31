"""BUG-36: undo/clone onto an open "as ~ enters, choose ..." choice must still let the permanent enter.

The pipeline used to keep its resume state in engine fields (a closure), so a restored `GameState` had an open choice
but nothing to continue it. The pending entry now lives in `GameState` (`pending_enter_choice` plus the spell / land /
token entry records), RULE 614.12 / 400.7, and the engine derives the open effect, the remaining queue and the exit
path from it.
"""
from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.game_session import GameSession

from test_mec134_named_card_statics import (
    _cast_through_the_session, _session_with_mage, bolt, game, put,
)

NAME_ANSWER = {"type": "choose", "free_text": True, "option_id": "Lightning Bolt"}


def _meddling_mage_on_battlefield(session):
    return [o for o in session.engine.state.battlefield if o.card.name == "Meddling Mage"]


def _opened_name_choice():
    session, mage, spell = _session_with_mage()
    _cast_through_the_session(session)
    assert session.engine.state.pending_choice["kind"] == "choose_card_name"
    return session


def test_rewinding_onto_the_open_name_choice_still_lets_the_mage_enter():
    session = _opened_name_choice()
    session.apply_action(NAME_ANSWER, "p1")
    assert _meddling_mage_on_battlefield(session)

    session.rewind(1)
    state = session.engine.state
    assert state.pending_choice["kind"] == "choose_card_name"
    assert state.pending_enter_choice is not None and state.pending_permanent_entry is not None
    assert not _meddling_mage_on_battlefield(session)

    session.apply_action(NAME_ANSWER, "p1")
    (mage,) = _meddling_mage_on_battlefield(session)
    assert mage.chosen_card_name == "Lightning Bolt"
    assert session.engine.state.pending_permanent_entry is None
    assert session.engine.state.pending_enter_choice is None


def test_rewinding_twice_then_casting_again_names_afresh():
    session = _opened_name_choice()
    session.apply_action(NAME_ANSWER, "p1")
    session.rewind(1)
    session.rewind(1)  # undo the cast itself
    assert not session.engine.state.pending_choice
    hand_mage = next(o for o in session.engine.state.player_by_id("p1").hand if o.card.name == "Meddling Mage")
    assert hand_mage.chosen_card_name is None
    session.engine.state.player_by_id("p1").mana_pool.add_many({"W": 1, "U": 1})
    _cast_through_the_session(session)
    session.apply_action({"type": "choose", "free_text": True, "option_id": "Shock"}, "p1")
    (mage,) = _meddling_mage_on_battlefield(session)
    assert mage.chosen_card_name == "Shock"


def test_a_cloned_state_answers_the_open_choice_on_a_fresh_engine():
    session = _opened_name_choice()
    clone = session.engine.state.clone()
    engine = GameEngine(clone)
    engine.resolve_pending_choice("Lightning Bolt")
    engine.resolve_until_stable()
    (mage,) = [o for o in clone.battlefield if o.card.name == "Meddling Mage"]
    assert mage.chosen_card_name == "Lightning Bolt"
    # The original is untouched and still waiting.
    assert session.engine.state.pending_choice["kind"] == "choose_card_name"
    assert not _meddling_mage_on_battlefield(session)


def _card(name, type_line, oracle, power=2):
    creature = "Creature" in type_line
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle, mana_cost_string="{1}",
                converted_mana_cost=1, is_creature=creature, is_land="Land" in type_line,
                power=power if creature else None, toughness=power if creature else None)


def _session_with(card):
    engine, state, p1, p2 = game()
    obj = put(engine, card, p1)
    put(engine, _card("Bear", "Creature — Bear", ""), p1, Zone.BATTLEFIELD)  # something to name a creature type from
    p1.mana_pool.add_many({"W": 3, "U": 3, "B": 3, "R": 3, "G": 3, "C": 3})
    return GameSession(engine, require_setup=False), obj


def _first_option(session):
    return session.engine.state.pending_choice["options"][0]["id"]


def test_a_creature_type_choice_survives_the_rewind():
    card = _card("Typed Golem", "Artifact Creature — Golem",
                 "As this creature enters, choose a creature type.\nCreatures you control of the chosen type get +1/+1.")
    session, _ = _session_with(card)
    _cast_through_the_session(session)
    assert session.engine.state.pending_choice["kind"] == "choose_creature_type"
    answer = {"type": "choose", "option_id": _first_option(session)}
    session.apply_action(answer, "p1")
    session.rewind(1)
    assert session.engine.state.pending_choice["kind"] == "choose_creature_type"
    session.apply_action(answer, "p1")
    (golem,) = [o for o in session.engine.state.battlefield if o.card.name == "Typed Golem"]
    assert golem.chosen_type == answer["option_id"]


def test_two_sequential_choices_resume_through_a_rewind_in_the_middle():
    card = _card("Dual Golem", "Artifact Creature — Golem",
                 "As this creature enters, choose a creature type.\nAs this creature enters, choose a color.\n"
                 "Creatures you control of the chosen type get +1/+1.")
    session, _ = _session_with(card)
    _cast_through_the_session(session)
    first = {"type": "choose", "option_id": _first_option(session)}
    session.apply_action(first, "p1")
    assert session.engine.state.pending_choice["kind"] == "choose_color"
    second = {"type": "choose", "option_id": "G"}
    session.apply_action(second, "p1")
    assert [o for o in session.engine.state.battlefield if o.card.name == "Dual Golem"]

    session.rewind(1)  # back onto the colour choice, with the type already stamped
    assert session.engine.state.pending_choice["kind"] == "choose_color"
    session.apply_action(second, "p1")
    (golem,) = [o for o in session.engine.state.battlefield if o.card.name == "Dual Golem"]
    assert golem.chosen_type == first["option_id"] and golem.chosen_color == "G"

    session.rewind(2)  # back onto the type choice
    assert session.engine.state.pending_choice["kind"] == "choose_creature_type"
    session.apply_action(first, "p1")
    session.apply_action(second, "p1")
    assert [o for o in session.engine.state.battlefield if o.card.name == "Dual Golem"]


def test_a_land_with_an_as_enters_choice_enters_after_a_rewind():
    land = _card("Typed Land", "Land", "As this land enters, choose a creature type.\n{T}: Add {C}.")
    session, obj = _session_with(land)
    play = next(a for a in session.legal_actions("p1") if a["type"] == "play_land")
    session.apply_action(play, "p1")
    state = session.engine.state
    assert state.pending_choice["kind"] == "choose_creature_type" and state.pending_land_entry is not None
    answer = {"type": "choose", "option_id": _first_option(session)}
    session.apply_action(answer, "p1")
    assert [o for o in session.engine.state.battlefield if o.card.name == "Typed Land"]

    session.rewind(1)
    assert session.engine.state.pending_choice["kind"] == "choose_creature_type"
    session.apply_action(answer, "p1")
    state = session.engine.state
    (entered,) = [o for o in state.battlefield if o.card.name == "Typed Land"]
    assert entered.chosen_type == answer["option_id"]
    assert state.pending_land_entry is None
    assert state.player_by_id("p1").lands_played_this_turn == 1


def test_a_token_with_an_as_enters_choice_enters_on_a_cloned_state_and_the_batch_continues():
    engine, state, p1, p2 = game()
    put(engine, _card("Bear", "Creature — Bear", ""), p1, Zone.BATTLEFIELD)
    token_card = _card("Typed Token", "Token Creature — Golem",
                       "As this creature enters, choose a creature type.")
    tokens = engine.rules.create_token("p1", token_card, 2)
    assert tokens == [] or len(tokens) < 2
    assert state.pending_choice["kind"] == "choose_creature_type" and state.pending_token_entry is not None

    clone = state.clone()
    cloned = GameEngine(clone)
    option = clone.pending_choice["options"][0]["id"]
    cloned.resolve_pending_choice(option)  # first token enters, the second one asks in turn
    assert clone.pending_choice["kind"] == "choose_creature_type"
    cloned.resolve_pending_choice(option)
    entered = [o for o in clone.battlefield if o.card.name == "Typed Token"]
    assert len(entered) == 2 and all(o.chosen_type == option for o in entered)
    assert clone.pending_token_entry is None and clone.pending_enter_choice is None
    # The original game kept its own pending entry and was not advanced by the clone.
    assert state.pending_token_entry is not None
    assert not [o for o in state.battlefield if o.card.name == "Typed Token"]


def test_an_answer_for_an_object_that_left_its_zone_visit_enters_nothing():
    session = _opened_name_choice()
    state = session.engine.state
    mage = state.pending_permanent_entry["obj"]
    mage.zone_incarnation += 1  # RULE 400.7: it is a new object now; the old choice must not stamp or admit it
    session.engine.resolve_pending_choice("Lightning Bolt")
    assert mage.chosen_card_name is None
    assert state.pending_enter_choice is None

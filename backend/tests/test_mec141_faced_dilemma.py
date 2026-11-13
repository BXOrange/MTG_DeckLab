"""MEC-141: facing a dilemma (RULE 700.17) -- the choke point, the per-turn tally, the FACED_DILEMMA event and its readers.

Real cached cards on a real engine. RULE 700.17: a player faces a dilemma whenever they choose one or more modes for a
spell or ability; the count is per spell/ability, not per mode.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.card_registry import is_registered
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from tests.support.card_cache import get_cached_card
from tests.support.star_trek import cast, game, on_battlefield, stock_library, vanilla

PARSER_MODELED = [
    "Elim Garak, Simple Tailor", "Obsidian Order Operative", "Seven of Nine", "Melkotian Adjudicator",
    "Gabriel Lorca, Mirror Menace", "The Caretaker",
]
HAND_AUTHORED = ["Captain Benjamin Sisko", "Jett Reno, Problem Solver", "Tell Me What You See"]

#: Modal-spell fixtures: "Dathon and Picard at El-Adrel" mode 0 is a single-target pump; Methods of the Mighty is a
#: "choose one or more" spell whose mode 2 needs no target.
DATHON = "Dathon and Picard at El-Adrel"
METHODS = "Methods of the Mighty"


def _card(name):
    card = get_cached_card(name)
    assert card is not None, name
    return card


def _faced(engine, player_id="p1"):
    return engine.state.dilemmas_faced_this_turn.get(player_id, 0)


def _events(engine):
    return [e for e in engine.state.events_this_turn() if e.type == EventType.FACED_DILEMMA]


def _answer(engine, option_id):
    choice = engine.state.pending_choice
    assert choice is not None and any(o["id"] == option_id for o in choice["options"]), choice
    engine.resolve_pending_choice(option_id)
    engine.resolve_until_stable()


@pytest.mark.parametrize("name", PARSER_MODELED)
def test_dilemma_cards_parse_as_modeled(name):
    assert parse_oracle(_card(name)).modeled


@pytest.mark.parametrize("name", HAND_AUTHORED)
def test_dilemma_cards_with_a_secondary_clause_are_hand_authored(name):
    assert is_registered(name)


# --- the choke point ----------------------------------------------------------------------------------------------

def test_a_modal_spell_is_one_dilemma():
    engine, p1, p2 = game(DATHON)
    bear = vanilla(engine, "p1")
    assert _faced(engine) == 0
    cast(engine, p1, p1.hand[0], targets=[bear], mode=0)
    assert _faced(engine) == 1 and _faced(engine, "p2") == 0
    (event,) = _events(engine)
    assert event.get("kind") == "spell" and event.get("mode_count") == 1


def test_choosing_several_modes_for_one_spell_is_still_one_dilemma():
    engine, p1, p2 = game(METHODS)
    foe = vanilla(engine, "p2", "Tapped Foe")
    foe.tapped = True
    cast(engine, p1, p1.hand[0], targets=[foe], mode=[1, 2])  # destroy a tapped creature AND +1/+1 counters
    assert _faced(engine) == 1
    assert _events(engine)[0].get("mode_count") == 2


def test_a_nonmodal_spell_faces_no_dilemma():
    engine, p1, p2 = game("Captain James T. Kirk")  # a creature spell: the modes belong to its enters trigger
    stock_library(engine, "p1", 3)
    p1.hand.append(GameObject(Card(id="F", name="Filler", type_line="Land", is_land=True), owner_id="p1", zone=Zone.HAND))
    cast(engine, p1, p1.hand[0])
    assert _faced(engine) == 0  # the spell had no modes; the trigger's mode prompt is still pending
    assert engine.state.pending_choice["kind"] == "trigger_mode"


def test_a_copy_copies_the_modes_and_faces_no_dilemma_of_its_own():
    engine, p1, p2 = game(DATHON)
    bear = vanilla(engine, "p1")
    p1.mana_pool.add_many({"C": 12, "W": 3, "U": 3, "B": 3, "R": 3, "G": 3})
    engine.cast_spell(p1, p1.hand[0], targets=[bear], mode=0)
    original = engine.state.stack[-1]
    engine.rules.copy_spell(original, "p1")
    assert len(engine.state.stack) == 2
    assert _faced(engine) == 1  # RULE 707.10: the copy has the same modes; nothing was chosen for it


def test_a_modal_trigger_is_one_dilemma_and_several_modes_still_one():
    # Captain Kirk with an empty hand: "choose one or more" (two modes picked, one dilemma).
    engine, p1, p2 = game("Captain James T. Kirk")
    stock_library(engine, "p1", 3)
    cast(engine, p1, p1.hand[0])
    assert _faced(engine) == 0  # still choosing
    _answer(engine, "1")
    if engine.state.pending_choice:
        _answer(engine, "2")
    if engine.state.pending_choice:
        _answer(engine, "done")
    assert _faced(engine) == 1
    assert _events(engine)[0].get("kind") == "triggered"


def test_a_modal_trigger_with_no_legal_mode_is_not_a_dilemma():
    engine, p1, p2 = game(via_steps=True)
    kms = on_battlefield(engine, "p1", "Kobayashi Maru Scenario")
    kms.triggered_abilities[0]._chosen_modes_permanent = {0, 1, 2, 3}  # every mode already chosen
    for pid in ("p1", "p2"):
        stock_library(engine, pid, 6)
    for _ in range(40):
        engine.advance_step()
        if engine.state.current_step == "upkeep" and engine.state.active_player.id == "p1":
            break
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None and _faced(engine) == 0


def test_a_modal_activated_ability_is_one_dilemma():
    engine, p1, p2 = game()
    jitte = on_battlefield(engine, "p1", "Umezawa's Jitte")
    bearer = vanilla(engine, "p1")
    engine.rules.attach_to_target(jitte, bearer)
    jitte.counters["charge"] = 2
    engine.activate_ability(p1, jitte, 0, mode=2)
    engine.resolve_until_stable()
    assert _faced(engine) == 1 and _events(engine)[0].get("kind") == "activated"
    engine.activate_ability(p1, jitte, 0, mode=0)
    assert _faced(engine) == 2


def test_the_tally_resets_next_turn_and_survives_clone():
    engine, p1, p2 = game(DATHON, via_steps=True)
    bear = vanilla(engine, "p1")
    cast(engine, p1, p1.hand[0], targets=[bear], mode=0)
    assert _faced(engine) == 1
    clone = engine.state.clone()
    assert clone.dilemmas_faced_this_turn.get("p1") == 1  # RULE 700.17: derived from the retained event log
    for pid in ("p1", "p2"):
        stock_library(engine, pid, 6)
    while engine.state.active_player.id == "p1":
        engine.advance_step()
    assert _faced(engine) == 0  # RULE 500: "this turn" ends with the turn


# --- the trigger head and its bodies -------------------------------------------------------------------------------

def test_garak_drains_two_whenever_you_face_a_dilemma():
    engine, p1, p2 = game(DATHON)
    on_battlefield(engine, "p1", "Elim Garak, Simple Tailor")
    bear = vanilla(engine, "p1")
    cast(engine, p1, p1.hand[0], targets=[bear], mode=0)
    assert (p1.life, p2.life) == (22, 18)


def test_an_opponents_dilemma_does_not_trigger_your_dilemma_cards():
    engine, p1, p2 = game(DATHON)
    on_battlefield(engine, "p2", "Obsidian Order Operative")  # p2's, and p1 is the one choosing
    bear = vanilla(engine, "p1")
    cast(engine, p1, p1.hand[0], targets=[bear], mode=0)
    assert (p1.life, p2.life) == (20, 20) and _faced(engine, "p2") == 0


def test_seven_of_nine_draws_and_melkotian_grows():
    engine, p1, p2 = game(DATHON)
    seven = on_battlefield(engine, "p1", "Seven of Nine")
    adjudicator = on_battlefield(engine, "p1", "Melkotian Adjudicator")
    stock_library(engine, "p1", 3)
    bear = vanilla(engine, "p1")
    hand_before = len(p1.hand)
    cast(engine, p1, p1.hand[0], targets=[bear], mode=0)
    assert len(p1.hand) == hand_before - 1 + 1 and adjudicator.counters.get("+1/+1") == 1
    assert seven in engine.state.battlefield


def test_jett_reno_grows_per_dilemma_and_draws_instead_of_surveiling_at_four_power():
    engine, p1, p2 = game(DATHON)
    jett = on_battlefield(engine, "p1", "Jett Reno, Problem Solver")
    bear = vanilla(engine, "p1")
    cast(engine, p1, p1.hand[0], targets=[bear], mode=0)
    assert jett.counters.get("+1/+1") == 1
    stock_library(engine, "p1", 3)
    hand_before, library_before = len(p1.hand), len(p1.library)
    engine.rules.set_tapped(jett, True)
    engine.resolve_until_stable()
    while engine.state.pending_choice:  # surveil 1 at power 2: a choice about the top card, no draw
        engine.resolve_pending_choice(engine.state.pending_choice["options"][0]["id"])
        engine.resolve_until_stable()
    assert len(p1.hand) == hand_before
    jett.counters["+1/+1"] = 3  # base 1 + 3 = power 4
    engine.recompute_continuous_effects()
    engine.rules.set_tapped(jett, False)
    engine.rules.set_tapped(jett, True)
    engine.resolve_until_stable()
    assert len(p1.hand) == hand_before + 1


def test_gabriel_lorca_returns_from_the_graveyard_for_b():
    engine, p1, p2 = game(DATHON)
    lorca = GameObject(_card("Gabriel Lorca, Mirror Menace"), owner_id="p1", zone=Zone.GRAVEYARD)
    lorca.controller_id = "p1"
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    bind_from_catalogue(lorca)
    p1.graveyard.append(lorca)
    bear = vanilla(engine, "p1")
    p1.mana_pool.add_many({"B": 1})
    cast(engine, p1, p1.hand[0], targets=[bear], mode=0)
    while engine.state.pending_choice:
        engine.resolve_pending_choice(engine.state.pending_choice["options"][0]["id"])
        engine.resolve_until_stable()
    assert lorca in p1.hand


def test_tell_me_what_you_see_bounces_itself_on_a_dilemma():
    engine, p1, p2 = game(DATHON)
    tell = on_battlefield(engine, "p1", "Tell Me What You See")
    bear = vanilla(engine, "p1")
    cast(engine, p1, p1.hand[0], targets=[bear], mode=0)
    while engine.state.pending_choice:
        engine.resolve_pending_choice(engine.state.pending_choice["options"][0]["id"])
        engine.resolve_until_stable()
    assert tell in p1.hand


def _tell_me_enters():
    engine, p1, p2 = game("Tell Me What You See")
    stock_library(engine, "p1", 3)
    cast(engine, p1, p1.hand[0])
    engine.resolve_pending_choice("p2")  # target opponent
    engine.resolve_until_stable()
    assert engine.state.pending_choice["kind"] == "pay_cost_then" and engine.state.pending_choice["player_id"] == "p2"
    return engine, p1, p2


def test_tell_me_what_you_see_opponent_lets_you_draw():
    engine, p1, p2 = _tell_me_enters()
    engine.resolve_pending_choice("pay")
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None and len(p1.hand) == 1 and p2.life == 20


def test_tell_me_what_you_see_opponent_declines_loses_four_and_you_surveil():
    engine, p1, p2 = _tell_me_enters()
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert p2.life == 16 and not p1.hand
    assert engine.state.pending_choice["kind"] == "surveil" and engine.state.pending_choice["player_id"] == "p1"


# --- the readers ------------------------------------------------------------------------------------------------------

def test_sisko_makes_an_officer_per_dilemma_at_your_end_step():
    engine, p1, p2 = game(DATHON, DATHON, via_steps=True)
    on_battlefield(engine, "p1", "Captain Benjamin Sisko")
    bear = vanilla(engine, "p1")
    for obj in list(p1.hand):
        cast(engine, p1, obj, targets=[bear], mode=0)
    assert _faced(engine) == 2
    for _ in range(20):
        if engine.state.current_step == "end":
            break
        engine.advance_step()
    engine.resolve_until_stable()
    assert len([o for o in engine.state.battlefield if o.name == "Officer" and o.is_token]) == 2


def test_the_caretaker_needs_a_dilemma_this_turn():
    engine, p1, p2 = game(DATHON, via_steps=True)
    caretaker = on_battlefield(engine, "p1", "The Caretaker")
    for pid in ("p1", "p2"):
        stock_library(engine, pid, 6, type_line="Creature")
    from mtg_analyzer.game import static_conditions
    cond = {"kind": "faced_dilemma_this_turn"}
    assert not static_conditions.condition_holds(cond, engine.state, caretaker, "p1")
    bear = vanilla(engine, "p1")
    cast(engine, p1, p1.hand[0], targets=[bear], mode=0)
    assert static_conditions.condition_holds(cond, engine.state, caretaker, "p1")
    assert not static_conditions.condition_holds(cond, engine.state, caretaker, "p2")


def _sisko_with_two_officers_and_a_stocked_library():
    engine, p1, p2 = game()
    sisko = on_battlefield(engine, "p1", "Captain Benjamin Sisko")  # an Officer himself: three Officers in all
    for name in ("Officer A", "Officer B"):
        obj = GameObject(Card(id=name, name=name, type_line="Creature — Human Officer", is_creature=True,
                              power=1, toughness=1), owner_id="p1", zone=Zone.BATTLEFIELD)
        obj.controller_id = "p1"
        engine.state.add_to_battlefield(obj)
    engine.recompute_continuous_effects()
    # The top of the library is the end of the list: Cheap3, Land, Big4, Cheap2, Cheap1.
    for name, mv in (("Cheap1", 1), ("Cheap2", 2), ("Big4", 4), ("Land", 0), ("Cheap3", 3)):
        card = (Card(id=name, name=name, type_line="Creature — Bear", is_creature=True, power=1, toughness=1,
                     converted_mana_cost=mv) if mv else Card(id=name, name=name, type_line="Land", is_land=True))
        p1.library.append(GameObject(card, owner_id="p1", zone=Zone.LIBRARY))
    return engine, p1, sisko


def test_sisko_exiles_five_and_offers_free_casts_up_to_the_officer_count():
    engine, p1, sisko = _sisko_with_two_officers_and_a_stocked_library()
    p1.mana_pool.add_many({"C": 2, "W": 1, "U": 1, "B": 1, "R": 1, "G": 1})
    engine.activate_ability(p1, sisko, 0)
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice["kind"] == "play_during_resolution" and choice["free"] and choice["repeat"]
    offered = sorted(engine.state.find_object(i).name for i in choice["instance_ids"])
    assert offered == ["Cheap1", "Cheap2", "Cheap3"]  # not the land, not mana value 4 > three Officers
    assert len(p1.exile) == 5
    for name in ("Cheap1", "Cheap3"):  # any number of them, no mana left to pay: the offer stays open for the rest
        engine.play_resolution_card(p1, next(o for o in p1.exile if o.name == name))
        assert engine.state.pending_choice["kind"] == "play_during_resolution"
    engine.resolve_pending_choice("decline")  # done casting
    engine.resolve_until_stable()
    assert {o.name for o in engine.state.battlefield} >= {"Cheap1", "Cheap3"}


def test_the_caretaker_exiles_until_a_nonland_card_and_lets_you_cast_it_after_a_dilemma():
    engine, p1, p2 = game(DATHON, via_steps=True)
    on_battlefield(engine, "p1", "The Caretaker")
    stock_library(engine, "p1", 6)
    prize = GameObject(Card(id="Prize", name="Prize", type_line="Creature — Bear", is_creature=True, power=3,
                            toughness=3, converted_mana_cost=3), owner_id="p2", zone=Zone.LIBRARY)
    stock_library(engine, "p2", 6)
    p2.library.append(prize)  # top card; the lands above it are not needed, it is the first nonland
    bear = vanilla(engine, "p1")
    cast(engine, p1, p1.hand[0], targets=[bear], mode=0)
    for _ in range(20):
        if engine.state.current_step == "end":
            break
        engine.advance_step()
    engine.resolve_until_stable()
    while engine.state.pending_choice:
        choice = engine.state.pending_choice
        if choice["kind"] == "trigger_target":
            engine.resolve_pending_choice("p2")
        elif choice["kind"] == "play_during_resolution":
            engine.play_resolution_card(p1, prize)
        else:
            engine.resolve_pending_choice(choice["options"][0]["id"])
        engine.resolve_until_stable()
    assert prize in engine.state.battlefield and prize.controller_id == "p1"


def test_the_caretaker_does_nothing_without_a_dilemma():
    engine, p1, p2 = game(via_steps=True)
    on_battlefield(engine, "p1", "The Caretaker")
    library_before = len(p2.library)
    for _ in range(20):
        if engine.state.current_step == "end":
            break
        engine.advance_step()
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None and not p2.exile and len(p2.library) == library_before


# --- the ticket's "Seven of Nine" secondary blocker: a durationless "base power and toughness become 7/9" ---------------

def _differently_named_lands(engine, count):
    for i in range(count):
        land = GameObject(Card(id=f"Land{i}", name=f"Distinct Land {i}", type_line="Land", is_land=True),
                          owner_id="p1", zone=Zone.BATTLEFIELD)
        land.controller_id = "p1"
        engine.state.add_to_battlefield(land)


def test_seven_of_nine_unassimilated_parses_and_becomes_seven_nine_only_with_seven_differently_named_lands():
    assert parse_oracle(_card("Seven of Nine, Unassimilated")).modeled
    engine, p1, p2 = game()
    seven = on_battlefield(engine, "p1", "Seven of Nine, Unassimilated")
    _differently_named_lands(engine, 6)
    p1.mana_pool.add_many({"C": 6, "U": 1})
    with pytest.raises(ValueError):
        engine.activate_ability(p1, seven, 0)  # six differently named lands: the condition fails
    _differently_named_lands(engine, 7)  # seven or more now (distinct names Distinct Land 0..6)
    engine.activate_ability(p1, seven, 0)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert (seven.power, seven.toughness) == (7, 9)
    # RULE 611.2a: no duration is stated, so it never ends; it is still 7/9 next turn.
    engine.state.internal_turn.number += 1
    engine.recompute_continuous_effects()
    assert (seven.power, seven.toughness) == (7, 9)

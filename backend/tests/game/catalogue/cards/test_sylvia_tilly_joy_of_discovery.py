"""Sylvia Tilly, Joy of Discovery: surveil 2 on entry; beginning-of-combat optional {1} + graveyard exile -> counter."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.star_trek import advance_to, game, stock_library, vanilla

NAME = "Sylvia Tilly, Joy of Discovery"
ORACLE = (
    "When Sylvia Tilly enters, surveil 2. (Look at the top two cards of your library, then put any number of them "
    "into your graveyard and the rest on top of your library in any order.)\n"
    "At the beginning of combat on your turn, you may pay {1} and exile a card from your graveyard. "
    "When you do, put a +1/+1 counter on target creature."
)


def _sylvia():
    return Card(id="sylvia", name=NAME, type_line="Legendary Creature — Human Scientist", is_creature=True,
                is_legendary=True, power=2, toughness=3, mana_cost_string="{1}{G}{U}", converted_mana_cost=3,
                oracle_text=ORACLE)


def _board(graveyard=2, library=6):
    engine, p1, p2 = game(via_steps=True, stop_at="upkeep")
    stock_library(engine, "p1", library)
    sylvia = GameObject(_sylvia(), owner_id="p1", zone=Zone.BATTLEFIELD)
    sylvia.controller_id = "p1"
    sylvia.summoning_sick = False
    bind_from_catalogue(sylvia)
    engine.state.add_to_battlefield(sylvia)
    for obj in stock_library(engine, "p1", graveyard, "Instant"):
        p1.library.remove(obj)
        obj.zone = Zone.GRAVEYARD
        p1.graveyard.append(obj)
    return engine, p1, p2, sylvia


def _forest(engine):
    """An untapped Forest: pool mana would empty between steps, so the payment comes from a land."""
    land = GameObject(Card(id="forest", name="Forest", type_line="Basic Land — Forest", is_land=True,
                           oracle_text="({T}: Add {G}.)"), owner_id="p1", zone=Zone.BATTLEFIELD)
    land.controller_id = "p1"
    bind_from_catalogue(land)
    engine.state.add_to_battlefield(land)
    return land


def _to_combat(engine):
    advance_to(engine, "begin_combat")
    engine.resolve_until_stable()


def test_specs_are_fresh_valid_and_bind():
    first, second = specs_for(_sylvia()), specs_for(_sylvia())
    assert first[0] is not second[0] and [s.ability_kind for s in first][:2] == ["triggered", "triggered"]
    for spec in first:
        spec.validate()
    assert len(_board()[3].triggered_abilities) == 2


def _answer(engine, kind, pick):
    """Answer the pending ``kind`` choice with the option id ``pick(choice)`` returns."""
    choice = engine.state.pending_choice
    assert choice and choice["kind"] == kind, choice
    engine.resolve_pending_choice(str(pick(choice)))


def _first(choice):
    return choice["options"][0]["id"]


def _pay_and_pick(engine, grave_card, target):
    """Pay {1}, exile ``grave_card`` from the graveyard, then target ``target`` with the reflexive counter."""
    _answer(engine, "pay_cost_then", lambda c: "pay")
    choice = engine.state.pending_choice
    if choice["kind"] == "choose_objects":  # forced (no prompt) when only one card qualifies
        _answer(engine, "choose_objects", lambda c: grave_card.instance_id)
        choice = engine.state.pending_choice
    assert choice, "the reflexive trigger asks for its target after the payment"
    engine.resolve_pending_choice(str(target.instance_id))
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()


@pytest.mark.parametrize("clone", [False, True])
def test_pay_exiles_the_chosen_graveyard_card_and_counters_the_chosen_creature(clone):
    engine, p1, p2, sylvia = _board()
    bear = vanilla(engine, "p1")
    land = _forest(engine)
    _to_combat(engine)
    if clone:
        engine = GameEngine(engine.state.clone())
        p1 = engine.state.player_by_id("p1")
        bear = engine.state.find_object(bear.instance_id)
        land = engine.state.find_object(land.instance_id)
    keep, exiled = p1.graveyard[0], p1.graveyard[1]
    _pay_and_pick(engine, exiled, bear)
    assert exiled.zone == Zone.EXILE and exiled not in p1.graveyard and keep in p1.graveyard
    assert land.tapped and bear.counters.get("+1/+1") == 1 and not sylvia.counters.get("+1/+1")


def test_the_counter_may_go_on_an_opponents_creature():
    engine, p1, p2, sylvia = _board(graveyard=1)
    _forest(engine)
    foe = vanilla(engine, "p2", "Foe")
    _to_combat(engine)
    _pay_and_pick(engine, p1.graveyard[0], foe)
    assert foe.counters.get("+1/+1") == 1


def test_declining_pays_nothing_and_exiles_nothing():
    engine, p1, p2, sylvia = _board()
    land = _forest(engine)
    _to_combat(engine)
    _answer(engine, "pay_cost_then", lambda c: "decline")
    engine.resolve_until_stable()
    assert not land.tapped and len(p1.graveyard) == 2 and not sylvia.counters.get("+1/+1")


def test_empty_graveyard_or_no_mana_makes_the_cost_unpayable():
    # No graveyard card: nothing to exile, so the payment is never offered and nothing is spent.
    engine, p1, p2, sylvia = _board(graveyard=0)
    land = _forest(engine)
    _to_combat(engine)
    assert not (engine.state.pending_choice or {}).get("kind") == "choose_objects"
    engine.resolve_until_stable()
    assert not land.tapped and not sylvia.counters.get("+1/+1")
    # A graveyard card but no mana: the card is not exiled either.
    engine, p1, p2, sylvia = _board(graveyard=1)
    _to_combat(engine)
    engine.resolve_until_stable()
    assert len(p1.graveyard) == 1 and not sylvia.counters.get("+1/+1")


def test_a_lone_graveyard_card_is_exiled_without_asking_which():
    engine, p1, p2, sylvia = _board(graveyard=1)
    _forest(engine)
    _to_combat(engine)
    card = p1.graveyard[0]
    _answer(engine, "pay_cost_then", lambda c: "pay")
    assert card.zone == Zone.EXILE


def test_only_the_controllers_own_turn_triggers_it():
    engine, p1, p2, sylvia = _board()
    _forest(engine)
    _to_combat(engine)
    _answer(engine, "pay_cost_then", lambda c: "decline")  # her own turn offers it
    engine.resolve_until_stable()
    for _ in range(40):  # bounded walk into the opponent's turn
        engine.advance_step()
        if engine.state.active_player.id == "p2" and engine.state.current_step == "begin_combat":
            break
    assert engine.state.active_player.id == "p2" and engine.state.current_step == "begin_combat"
    engine.resolve_until_stable()
    assert not engine.state.pending_choice


def test_entry_surveils_two():
    engine, p1, p2 = game(via_steps=False)
    stock_library(engine, "p1", 4)
    sylvia = GameObject(_sylvia(), owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(sylvia, Zone.HAND)
    bind_from_catalogue(sylvia)
    from tests.support.star_trek import cast
    cast(engine, p1, sylvia)
    choice = engine.state.pending_choice
    assert choice and "surveil" in choice["kind"], choice

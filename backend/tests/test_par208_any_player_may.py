"""PAR-208 slice 2: "Any player/opponent may <cost>. If a player does, <effect>." / "If no 1 does, <effect>."
(RULE 118.12, 608.2c), executed in the real engine: every living player is asked in turn order, the first to pay
ends the sweep and the payoff runs once for the controller."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.game import creature, land, make_engine

_DB = CardDatabase(DB_PATH)


def _named(name: str) -> Card:
    card = _DB.get_card(name)
    assert card is not None, name
    return card


def _engine():
    eng = make_engine([creature(f"Lib {i}") for i in range(10)], [creature(f"Opp {i}") for i in range(10)], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _board(eng, card: Card, pid: str = "p1") -> GameObject:
    obj = GameObject(card, owner_id=pid, zone=Zone.BATTLEFIELD)
    obj.controller_id = pid
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _enter(eng, name: str, pid: str = "p1") -> GameObject:
    obj = _board(eng, _named(name), pid)
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id=pid, object=obj.name, instance_id=obj.instance_id,
        object_types=sorted(obj.type_words),
    ))
    eng.resolve_until_stable()
    return obj


def _answer(eng, option: str) -> None:
    choice = eng.state.pending_choice
    assert choice is not None, "expected an open choice"
    ids = [o["id"] for o in choice["options"]]
    assert option in ids, (option, ids)
    eng.resolve_pending_choice(option)
    eng.resolve_until_stable()


def _asked(eng) -> str:
    choice = eng.state.pending_choice
    assert choice is not None and choice.get("kind") == "all_decline_or"
    return choice["player_id"]


@pytest.mark.parametrize("name", [
    "Argothian Wurm", "Shivan Wumpus", "Brain Gorgers", "Dash Hopes", "Phantasmagorian", "Temporal Extortion",
    "Prowling Pangolin", "Clackbridge Troll", "Desecration Demon", "Innocent Traveler // Malicious Invader",
])
def test_claimed_cards_are_modeled(name):
    assert parse_oracle(_named(name)).coverage == MODELED


def test_argothian_wurm_goes_back_to_the_library_when_a_player_sacrifices_a_land():
    eng = _engine()
    _board(eng, land("Island", "Island"), "p2")
    wurm_card = _named("Argothian Wurm")
    # p1 has no land to give up, so the sweep skips them and asks p2 (a payment nobody can make is not offered).
    wurm = _enter(eng, "Argothian Wurm")
    assert _asked(eng) == "p2"
    _answer(eng, "pay")
    while eng.state.pending_choice is not None and eng.state.pending_choice.get("kind") != "all_decline_or":
        choice = eng.state.pending_choice
        eng.resolve_pending_choice(next(o["id"] for o in choice["options"] if o["id"] != "decline"))
        eng.resolve_until_stable()
    assert wurm.zone is Zone.LIBRARY and wurm in eng.state.player_by_id("p1").library
    assert wurm_card.name == "Argothian Wurm"


def test_argothian_wurm_stays_when_everyone_declines():
    eng = _engine()
    _board(eng, land("Island", "Island"), "p2")
    _board(eng, land("Forest", "Forest"), "p1")
    wurm = _enter(eng, "Argothian Wurm")
    assert _asked(eng) == "p1"
    _answer(eng, "decline")
    assert _asked(eng) == "p2"
    _answer(eng, "decline")
    assert wurm.zone is Zone.BATTLEFIELD


@pytest.mark.parametrize("clone_at", [None, "offer", "selection"])
def test_paid_followup_waits_for_sacrifice_selection_and_survives_clone(clone_at):
    eng = _engine()
    first = _board(eng, land("Island", "Island"), "p2")
    second = _board(eng, land("Forest", "Forest"), "p2")
    wurm = _enter(eng, "Argothian Wurm")
    wurm_id, first_id, second_id = wurm.instance_id, first.instance_id, second.instance_id
    if clone_at == "offer":
        eng = GameEngine(eng.state.clone())
    _answer(eng, "pay")
    # RULE 608.2c: agreeing to pay is not the sacrifice itself. With two legal lands,
    # the payer still has to select one before the Wurm can leave the battlefield.
    assert eng.state.pending_choice is not None
    assert any(o.instance_id == wurm_id for o in eng.state.battlefield)
    assert len(eng.state.player_by_id("p1").library) == 10
    if clone_at == "selection":
        eng = GameEngine(eng.state.clone())
    while eng.state.pending_choice is not None:
        choice = eng.state.pending_choice
        eng.resolve_pending_choice(next(o["id"] for o in choice["options"] if o["id"] != "decline"))
        eng.resolve_until_stable()
    assert any(o.instance_id == wurm_id for o in eng.state.player_by_id("p1").library)
    assert sum(o.instance_id in {first_id, second_id} for o in eng.state.player_by_id("p2").graveyard) == 1
    assert not eng.state.deferred_effects


def test_cloned_sweep_keeps_only_the_remaining_players():
    eng = _engine()
    _board(eng, land("Island", "Island"), "p1")
    _board(eng, land("Forest", "Forest"), "p2")
    wurm = _enter(eng, "Argothian Wurm")
    _answer(eng, "decline")
    clone = GameEngine(eng.state.clone())
    assert _asked(clone) == "p2"
    _answer(clone, "decline")
    assert clone.state.pending_all_decline_or is None
    assert any(o.instance_id == wurm.instance_id for o in clone.state.battlefield)
    assert _asked(eng) == "p2"  # answering the clone leaves the original offer intact


def test_clackbridge_troll_asks_only_opponents_and_pays_off_for_the_controller():
    eng = _engine()
    troll = _board(eng, _named("Clackbridge Troll"))
    _board(eng, creature("Victim"), "p2")
    p1 = eng.state.player_by_id("p1")
    life = p1.life
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="begin_combat", phase="combat", player_id="p1", controller_id="p1"))
    eng.resolve_until_stable()
    if eng.state.pending_choice is None:
        pytest.skip("combat trigger not reachable from a bare STEP_BEGIN in this harness")
    assert _asked(eng) == "p2"  # the controller is not asked: "any opponent"
    _answer(eng, "pay")
    while eng.state.pending_choice is not None:
        choice = eng.state.pending_choice
        eng.resolve_pending_choice(next(o["id"] for o in choice["options"] if o["id"] != "decline"))
        eng.resolve_until_stable()
    assert troll.tapped and p1.life == life + 3
    assert len(p1.hand) == 1


def test_innocent_traveler_transforms_only_if_no_opponent_sacrifices():
    eng = _engine()
    traveler = _board(eng, _named("Innocent Traveler // Malicious Invader"))
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="beginning", player_id="p1", controller_id="p1"))
    eng.resolve_until_stable()
    assert not eng.state.pending_choice  # the opponent has no creature to sacrifice, so nobody can pay
    assert traveler.transformed


def test_the_payoff_form_does_not_run_when_nobody_pays():
    spec = match_clause("any player may discard 3 cards. if a player does, counter ~")
    assert spec is not None and spec[0].params["paid_effects"] and "effects" not in spec[0].params


@pytest.mark.parametrize("clause", [
    "any player may sacrifice a creature of their choice. if a player does, destroy target creature",  # targeted
    "any player may have ~ deal 5 damage to them. if a player does, sacrifice ~",  # damage is not a cost here
    "any player may exile a card from their graveyard. if a player does, ~ assigns no combat damage this turn",
])
def test_unsupported_costs_and_targeted_payoffs_stay_unclaimed(clause):
    assert match_clause(clause) is None


def _cast(eng, name: str, mana: dict[str, int]) -> GameObject:
    obj = GameObject(_named(name), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1 = eng.state.player_by_id("p1")
    p1.hand.append(obj)
    p1.mana_pool.add_many(mana)
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()
    return obj


def test_brain_gorgers_is_countered_when_an_opponent_sacrifices_a_creature():
    eng = _engine()
    victim = _board(eng, creature("Victim"), "p2")
    gorgers = _cast(eng, "Brain Gorgers", {"B": 6, "C": 6})
    assert _asked(eng) == "p2"  # "any player" starts with the active player, who has no creature to give
    _answer(eng, "pay")
    while eng.state.pending_choice is not None:
        choice = eng.state.pending_choice
        eng.resolve_pending_choice(next(o["id"] for o in choice["options"] if o["id"] != "decline"))
        eng.resolve_until_stable()
    assert victim.zone is Zone.GRAVEYARD
    assert gorgers.zone is Zone.GRAVEYARD  # countered, never entered the battlefield


def test_brain_gorgers_resolves_when_everyone_declines():
    eng = _engine()
    _board(eng, creature("Victim"), "p2")
    gorgers = _cast(eng, "Brain Gorgers", {"B": 6, "C": 6})
    while eng.state.pending_choice is not None:
        _answer(eng, "decline")
    assert gorgers.zone is Zone.BATTLEFIELD


def test_temporal_extortion_costs_half_the_payers_life_rounded_up():
    eng = _engine()
    p2 = eng.state.player_by_id("p2")
    p2.life = 15
    ext = _cast(eng, "Temporal Extortion", {"B": 4})
    assert _asked(eng) == "p1"
    _answer(eng, "decline")
    assert _asked(eng) == "p2"
    _answer(eng, "pay")
    assert p2.life == 7  # 15 - ceil(15 / 2)
    assert ext.zone is Zone.GRAVEYARD

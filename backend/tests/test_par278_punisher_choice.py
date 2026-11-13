"""PAR-278: "Target opponent may have you <benefit>. If they don't, <penalty>." (the punisher choice).

RULE 608.2d: the targeted opponent decides, on resolution, whether the ability's controller gets the benefit; RULE
608.2b: if that sole target has become illegal nothing happens. Parsed onto `pay_cost_then` with ``payer="target"``
and an empty cost (the shape Combustible Gearhulk / Tell Me What You See are hand-authored in), then executed in the
real engine with the opponent answering yes and no."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.game import creature, make_engine

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


def _enter(eng, name: str, pid: str = "p1") -> GameObject:
    obj = GameObject(_named(name), owner_id=pid, zone=Zone.BATTLEFIELD)
    obj.controller_id = pid
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id=pid, object=obj.name, instance_id=obj.instance_id,
        object_types=sorted(obj.type_words),
    ))
    eng.resolve_until_stable()
    return obj


def _pick_opponent(eng) -> None:
    """The enters trigger announces its RULE 115 target (the only opponent is offered)."""
    choice = eng.state.pending_choice
    if choice is not None and any(o["id"] == "p2" for o in choice.get("options", [])):
        eng.resolve_pending_choice("p2")
        eng.resolve_until_stable()


def _opponent_answers(eng, answer: str) -> None:
    _pick_opponent(eng)
    choice = eng.state.pending_choice
    assert choice is not None, "the opponent should be asked"
    assert choice["player_id"] == "p2", "the targeted opponent (not the controller) decides"
    eng.resolve_pending_choice(answer)
    eng.resolve_until_stable()


@pytest.mark.parametrize("name", ["Terrapact Intimidator", "Shakedown Heavy", "Tell Me What You See"])
def test_claimed_cards_are_modeled(name):
    assert parse_oracle(_named(name)).coverage == MODELED


def _strip_prompt(params):
    return {k: v for k, v in params.items() if k != "prompt"}


def test_tell_me_what_you_see_parses_to_the_hand_authored_shape():
    from mtg_analyzer.game.card_catalogue.t.tell_me_what_you_see import _tell_me_what_you_see

    parsed = parse_oracle(_named("Tell Me What You See")).specs[0].effects[0]
    authored = _tell_me_what_you_see()[0].effects[0]
    assert parsed.type == authored.type == "pay_cost_then"
    assert _strip_prompt(parsed.params) == _strip_prompt(authored.params)


def test_terrapact_intimidator_parses_onto_pay_cost_then_with_an_empty_cost():
    spec = parse_oracle(_named("Terrapact Intimidator")).specs[0].effects[0]
    assert spec.type == "pay_cost_then"
    assert spec.params["payer"] == "target" and spec.params["target_kind"] == "opponent"
    assert spec.params["cost"] == ""
    assert [e["type"] for e in spec.params["effects"]] == ["create_token"]
    assert [e["type"] for e in spec.params["else_effects"]] == ["add_counters"]


def test_terrapact_intimidator_opponent_says_yes_controller_gets_landers_not_counters():
    eng = _engine()
    intimidator = _enter(eng, "Terrapact Intimidator")
    _opponent_answers(eng, "pay")
    landers = [o for o in eng.state.battlefield if o.controller_id == "p1" and o.name == "Lander"]
    assert len(landers) == 2
    assert intimidator.counters.get("+1/+1", 0) == 0


def test_terrapact_intimidator_opponent_says_no_controller_gets_counters_not_landers():
    eng = _engine()
    intimidator = _enter(eng, "Terrapact Intimidator")
    _opponent_answers(eng, "decline")
    assert not [o for o in eng.state.battlefield if o.name == "Lander"]
    assert intimidator.counters.get("+1/+1", 0) == 2


def test_tell_me_what_you_see_no_costs_them_four_life_yes_draws_you_a_card():
    eng = _engine()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    hand, life = len(p1.hand), p2.life
    _enter(eng, "Tell Me What You See")
    _opponent_answers(eng, "pay")
    assert len(p1.hand) == hand + 1 and p2.life == life
    eng2 = _engine()
    q1, q2 = eng2.state.player_by_id("p1"), eng2.state.player_by_id("p2")
    hand, life = len(q1.hand), q2.life
    _enter(eng2, "Tell Me What You See")
    _opponent_answers(eng2, "decline")
    assert len(q1.hand) == hand and q2.life == life - 4


def test_target_gone_before_resolution_neither_branch_happens():
    """RULE 608.2b: the ability's only target (the opponent) is no longer a legal target, so it does nothing."""
    eng = _engine()
    p2 = eng.state.player_by_id("p2")
    p2.has_lost = True
    obj = GameObject(_named("Terrapact Intimidator"), owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id="p1", object=obj.name, instance_id=obj.instance_id,
        object_types=sorted(obj.type_words),
    ))
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None
    assert obj.counters.get("+1/+1", 0) == 0 and not [o for o in eng.state.battlefield if o.name == "Lander"]


def test_unparsed_penalty_leaves_the_card_unclaimed():
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    assert parse_effect_body(
        "target opponent may have you draw a card. if they don't, frobnicate the wibble.",
    ) is None


def _combat_engine():
    eng = make_engine([creature(f"Lib {i}") for i in range(10)], [creature(f"Opp {i}") for i in range(10)], hand=0)
    eng.start()
    return eng


def _shakedown_attack(eng):
    """The active player attacks the other with Shakedown Heavy; returns (heavy, attacker id, defender id)."""
    attacker = eng.state.active_player.id
    defender = next(p.id for p in eng.state.players if p.id != attacker)
    heavy = GameObject(_named("Shakedown Heavy"), owner_id=attacker, zone=Zone.BATTLEFIELD)
    heavy.controller_id = attacker
    heavy.summoning_sick = False
    eng.state.add_to_battlefield(heavy)
    bind_from_catalogue(heavy)
    while eng.state.current_step != "declare_attackers":
        eng.advance_step()
    assert eng.state.active_player.id == attacker
    eng.declare_attackers(eng.state.active_player, [
        {"attacker": heavy, "defender": {"kind": "player", "id": defender}}])
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    return heavy, attacker, defender


def test_shakedown_heavy_defender_says_yes_you_draw_and_it_leaves_combat_untapped():
    # The defending player decides (RULE 608.2d); "if they do" the draw, the untap and the removal all happen.
    eng = _combat_engine()
    heavy, attacker, defender = _shakedown_attack(eng)
    hand = len(eng.state.player_by_id(attacker).hand)
    choice = eng.state.pending_choice
    assert choice is not None and choice["player_id"] == defender
    eng.resolve_pending_choice("pay")
    eng.resolve_until_stable()
    assert len(eng.state.player_by_id(attacker).hand) == hand + 1
    assert not heavy.tapped and not heavy.attacking


def test_shakedown_heavy_defender_says_no_nothing_happens():
    eng = _combat_engine()
    heavy, attacker, defender = _shakedown_attack(eng)
    hand = len(eng.state.player_by_id(attacker).hand)
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    assert len(eng.state.player_by_id(attacker).hand) == hand and heavy.tapped

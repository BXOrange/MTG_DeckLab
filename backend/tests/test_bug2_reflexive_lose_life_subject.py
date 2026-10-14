"""BUG-2: "target player draws N cards and loses N life" -- the subject-less "and loses ..."
must hit the *targeted* player (RULE 115 / 608.2c), also inside a reflexive "when you do"
trigger (Unscrupulous Contractor) and an exploit trigger (Fell Stinger), not the controller."""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

DRAWN = 2
LOST = 2
START_LIFE = 20


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])],
                              starting_life=START_LIFE, starting_hand=0)
    for pid in ("p1", "p2"):
        pl = eng.state.player_by_id(pid)
        for i in range(5):
            pl.library.append(GameObject(
                Card(id=f"f{pid}{i}", name=f"Filler {pid}{i}", type_line="Creature — Bear",
                     is_creature=True, power=1, toughness=1),
                owner_id=pid, zone=Zone.LIBRARY))
    return eng


def _fodder(eng):
    obj = GameObject(Card(id="fod", name="Fodder", type_line="Creature — Bear",
                          is_creature=True, power=1, toughness=1),
                     owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _enter(eng, name):
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    assert card is not None and parse_oracle(card).modeled
    p1 = eng.state.player_by_id("p1")
    obj = GameObject(card, owner_id="p1", controller_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    p1.remove_from_zone(obj, Zone.HAND)
    eng.rules._put_searched_card(p1, obj, "battlefield")
    eng.resolve_until_stable()
    return obj


def _assert_opponent_hit(eng):
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    assert len(p2.hand) == DRAWN and p2.life == START_LIFE - LOST
    assert len(p1.hand) == 0 and p1.life == START_LIFE


def _answer_until_target(eng, victim):
    """Answer the sacrifice prompt, then the trigger's player target with the opponent."""
    for _ in range(4):
        choice = eng.state.pending_choice
        if choice is None:
            eng.resolve_until_stable()
            continue
        if choice["kind"] == "trigger_target":
            eng.resolve_pending_choice("p2")
        elif any(o.get("instance_id") == victim.instance_id for o in choice["options"]):
            eng.resolve_pending_choice(victim.instance_id)
        else:
            eng.resolve_pending_choice("pay")
        eng.resolve_until_stable()
    assert eng.state.pending_choice is None


def test_unscrupulous_contractor_reflexive_trigger_hits_target_player():
    eng = _engine()
    victim = _fodder(eng)
    _enter(eng, "Unscrupulous Contractor")
    _answer_until_target(eng, victim)
    assert victim.zone == Zone.GRAVEYARD
    _assert_opponent_hit(eng)


def test_fell_stinger_exploit_trigger_hits_target_player():
    eng = _engine()
    victim = _fodder(eng)
    _enter(eng, "Fell Stinger")
    _answer_until_target(eng, victim)
    assert victim.zone == Zone.GRAVEYARD
    _assert_opponent_hit(eng)

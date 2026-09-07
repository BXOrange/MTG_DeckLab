"""Secrets of Strixhaven — playability batch, wave 20.

Wave 20 (PARSER_VERSION 296 -> 297): "<creature> deals damage to itself
equal to its power." `DamageEqualToPowerEffect` gained a ``to_self`` flag:
the dealer is also the recipient (no second target), and the "each
creature" mass form (Wave of Reckoning / Solar Blaze) has no dealer target
at all — every creature reads its *own* power.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.effect_binder import build_effects
from mtg_analyzer.game.effects import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def test_target_self_damage_clause():
    specs = match_clause("target creature deals damage to itself equal to its power")
    assert specs == [EffectSpec("damage_equal_to_power", {
        "dealer_kind": "creature", "target_kind": None, "to_self": True,
    })]


def test_each_creature_self_damage_clause():
    specs = match_clause("each creature deals damage to itself equal to its power")
    assert specs == [EffectSpec("damage_equal_to_power", {
        "selector": "each_creature", "target_kind": None, "to_self": True,
    })]


def test_adversarial_not_claimed():
    # "to another target" is the ordinary one-sided fight, not to-self.
    assert match_clause(
        "target creature deals damage to any target equal to its power"
    ) is None


@pytest.mark.parametrize("name", [
    "Wave of Reckoning", "Solar Blaze", "Justice Strike", "Inner Struggle",
    "Wrack with Madness", "Repentance", "Kiku's Shadow",
])
def test_real_cards_modeled(name):
    r = parse_oracle(_db().get_card(name))
    assert r.coverage != UNMODELED, r.unclaimed


def _mk(eng, oid, pw, tf, owner):
    o = GameObject(
        card=Card(id=oid, name=oid, type_line="Creature — X",
                  is_creature=True, power=pw, toughness=tf),
        owner_id=owner.id, zone=Zone.BATTLEFIELD,
    )
    o.controller_id = owner.id
    eng.state.add_to_battlefield(o)
    return o


def test_each_creature_self_damage_runtime():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    p2 = [p for p in eng.state.players if p.id != p1.id][0]
    big = _mk(eng, "big", 3, 5, p1)      # survives its own 3
    small = _mk(eng, "small", 1, 1, p1)  # dies to its own 1
    theirs = _mk(eng, "theirs", 4, 2, p2)  # dies to its own 4
    eng.recompute_continuous_effects()

    src = GameObject(card=Card(id="wor", name="Wave of Reckoning", type_line="Sorcery"),
                     owner_id=p1.id, zone=Zone.STACK)
    src.controller_id = p1.id
    effs = build_effects([EffectSpec("damage_equal_to_power", {
        "selector": "each_creature", "target_kind": None, "to_self": True})], src)
    ctx = GameContext(state=eng.state, engine=eng.rules)
    for e in effs:
        e.apply(ctx, [])
    eng.rules.check_state_based_actions()

    assert big in eng.state.permanents() and big.damage_marked == 3
    assert small not in eng.state.permanents()
    assert theirs not in eng.state.permanents()


def test_target_self_damage_runtime():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    p2 = [p for p in eng.state.players if p.id != p1.id][0]
    victim = _mk(eng, "victim", 5, 6, p2)
    bystander = _mk(eng, "bystander", 2, 2, p2)
    eng.recompute_continuous_effects()

    src = GameObject(card=Card(id="js", name="Justice Strike", type_line="Instant"),
                     owner_id=p1.id, zone=Zone.STACK)
    src.controller_id = p1.id
    effs = build_effects([EffectSpec("damage_equal_to_power", {
        "dealer_kind": "creature", "target_kind": None, "to_self": True})], src)
    ctx = GameContext(state=eng.state, engine=eng.rules)
    for e in effs:
        e.apply(ctx, [victim])
    eng.rules.check_state_based_actions()

    assert victim.damage_marked == 5
    assert bystander.damage_marked == 0

"""PAR-30 — RULE 701.10 exchange-control residue: the cross-target legality
predicates RULE 115 verifies at selection, checked at resolution instead
(`effects.ExchangeControlEffect._cross_target_ok`, the same documented
simplification the pre-existing different-controllers no-op already is).

- ``shares_type`` — "…that share[s] a card type with it" (Daring Thief,
  Legerdemain, Role Reversal, Shifting Loyalties).
- ``second_not_greater="mana_value"`` — "…with equal or lesser mana value"
  (Puca's Mischief).
- ``second_not_greater="power"`` — "…with power less than or equal to that
  creature's power" (Spawnbroker).
"""

from __future__ import annotations

from mtg_analyzer.game.effects import ExchangeControlEffect, GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _permanent(name, controller, type_line="Artifact", **kw):
    card = Card(id=name, name=name, type_line=type_line,
                is_creature="Creature" in type_line, **kw)
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    return obj


def _ctx():
    p1, p2 = Player(id="p1", life=20), Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    engine = GameEngine(state)
    engine.state.current_step = "main1"
    return GameContext(state, engine.rules), state


# --- shares_type -----------------------------------------------------------


def test_shares_type_swaps_when_a_card_type_is_shared():
    ctx, state = _ctx()
    mine = _permanent("MyArt", "p1", "Artifact Creature — Golem")
    theirs = _permanent("TheirCreature", "p2", "Creature — Bear")
    state.battlefield.extend([mine, theirs])

    ExchangeControlEffect(
        first_target_kind="nonland_permanent_you_control",
        target_kind="permanent_you_dont_control", shares_type="card",
    ).apply(ctx, targets=[mine, theirs])

    assert mine.controller_id == "p2" and theirs.controller_id == "p1"


def test_shares_type_no_ops_when_no_card_type_is_shared():
    ctx, state = _ctx()
    mine = _permanent("MyArt", "p1", "Artifact")
    theirs = _permanent("TheirCreature", "p2", "Creature — Bear")
    state.battlefield.extend([mine, theirs])

    ExchangeControlEffect(
        first_target_kind="nonland_permanent_you_control",
        target_kind="permanent_you_dont_control", shares_type="card",
    ).apply(ctx, targets=[mine, theirs])

    assert mine.controller_id == "p1" and theirs.controller_id == "p2"


def test_shares_type_multi_count_mode():
    ctx, state = _ctx()
    a = _permanent("A", "p1", "Enchantment")
    b = _permanent("B", "p2", "Artifact Enchantment")
    state.battlefield.extend([a, b])

    ExchangeControlEffect(target_kind="permanent", count=2, shares_type="card").apply(
        ctx, targets=[a, b]
    )
    assert a.controller_id == "p2" and b.controller_id == "p1"


# --- second_not_greater: mana_value -------------------------------------------


def test_mana_value_cap_swaps_when_theirs_is_not_greater():
    ctx, state = _ctx()
    mine = _permanent("Mine", "p1", "Artifact", converted_mana_cost=4)
    theirs = _permanent("Theirs", "p2", "Artifact", converted_mana_cost=4)
    state.battlefield.extend([mine, theirs])

    ExchangeControlEffect(
        first_target_kind="nonland_permanent_you_control",
        target_kind="nonland_permanent_you_dont_control",
        second_not_greater="mana_value",
    ).apply(ctx, targets=[mine, theirs])

    assert mine.controller_id == "p2" and theirs.controller_id == "p1"


def test_mana_value_cap_no_ops_when_theirs_is_greater():
    ctx, state = _ctx()
    mine = _permanent("Mine", "p1", "Artifact", converted_mana_cost=2)
    theirs = _permanent("Theirs", "p2", "Artifact", converted_mana_cost=5)
    state.battlefield.extend([mine, theirs])

    ExchangeControlEffect(
        first_target_kind="nonland_permanent_you_control",
        target_kind="nonland_permanent_you_dont_control",
        second_not_greater="mana_value",
    ).apply(ctx, targets=[mine, theirs])

    assert mine.controller_id == "p1" and theirs.controller_id == "p2"


# --- second_not_greater: power ----------------------------------------------


def test_power_cap_swaps_and_no_ops():
    for their_power, swaps in ((3, True), (4, False)):
        ctx, state = _ctx()
        mine = _permanent("Mine", "p1", "Creature — Bear", power=3, toughness=3)
        theirs = _permanent("Theirs", "p2", "Creature — Ogre",
                            power=their_power, toughness=3)
        state.battlefield.extend([mine, theirs])

        ExchangeControlEffect(
            first_target_kind="creature_you_control",
            target_kind="creature_you_dont_control", second_not_greater="power",
        ).apply(ctx, targets=[mine, theirs])

        assert (mine.controller_id == "p2") is swaps


# --- real cards parse -----------------------------------------------------------


def test_real_exchange_control_residue_cards_modeled():
    db = CardDatabase(DEFAULT_DB_PATH)
    expected = {
        "Role Reversal": {"target_kind": "permanent", "count": 2, "shares_type": "card"},
        "Shifting Loyalties": {"target_kind": "permanent", "count": 2, "shares_type": "card"},
        "Legerdemain": {"first_target_kind": "permanent", "target_kind": "permanent",
                        "shares_type": "card"},
        "Daring Thief": {"first_target_kind": "nonland_permanent_you_control",
                         "target_kind": "permanent_you_dont_control", "shares_type": "card"},
        "Puca's Mischief": {"first_target_kind": "nonland_permanent_you_control",
                            "target_kind": "nonland_permanent_you_dont_control",
                            "second_not_greater": "mana_value"},
        "Spawnbroker": {"first_target_kind": "creature_you_control",
                        "target_kind": "creature_you_dont_control",
                        "second_not_greater": "power"},
    }
    for name, params in expected.items():
        r = parse_oracle(db.get_card(name))
        assert r.coverage != UNMODELED, (name, r.unclaimed)
        ec = next(e for s in r.specs for e in s.effects if e.type == "exchange_control")
        assert ec.params == params, (name, ec.params)

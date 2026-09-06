"""PAR-29 — RULE 701.35 Detain (Return to Ravnica).

A designation like goad/suspect: `GameObject.detained_by` (a per-detainer
set, expiring "until your next turn" via the same `GameEngine.begin_turn`
sweep goad uses). RULE 701.35b's three consequences — can't attack, can't
block, activated abilities can't be activated — are enforced in `_can_attack`
/ `can_block` / `can_activate` via `combat.is_detained`.

Reference: game/rules/misc_mixin.py (`detain`), game/combat.py
(`is_detained`), game/effects.py (`DetainEffect`),
parser/oracle/catalogue/handlers.py.
"""

from __future__ import annotations

from mtg_analyzer.game import combat
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


# --- parse ---------------------------------------------------------------


def test_detain_shapes_parse():
    assert match_clause("detain target creature an opponent controls") == [
        EffectSpec("detain", {"target_kind": "creature_you_dont_control"})
    ]
    assert match_clause("detain target nonland permanent an opponent controls") == [
        EffectSpec("detain", {"target_kind": "nonland_permanent_you_dont_control"})
    ]
    assert match_clause("detain up to two target creatures your opponents control") == [
        EffectSpec("detain", {"target_kind": "creature_you_dont_control",
                              "count": 2, "optional": True})
    ]
    # not a real printing — no controller qualifier
    assert match_clause("detain target creature") is None


def test_real_detain_cards_modeled_end_to_end():
    arrester = Card(id="AA", name="Azorius Arrester",
                    type_line="Creature — Human Soldier", is_creature=True,
                    power=2, toughness=1,
                    oracle_text="When this creature enters, detain target creature "
                                "an opponent controls. (Until your next turn, that "
                                "creature can't attack or block and its activated "
                                "abilities can't be activated.)")
    decree = Card(id="LD", name="Lyev Decree", type_line="Sorcery", is_sorcery=True,
                  oracle_text="Detain up to two target creatures your opponents control.")
    assert parse_oracle(arrester).modeled
    assert parse_oracle(decree).modeled


# --- execute -----------------------------------------------------------------


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _creature(name, owner, power=2, tough=2):
    card = Card(id=name, name=name, type_line="Creature — Bear",
                is_creature=True, power=power, toughness=tough)
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    obj.summoning_sick = False
    return obj


def test_detain_sets_flag_and_fires_event():
    eng, state = _engine()
    c = _creature("C", "p2")
    state.add_to_battlefield(c)
    fired = []
    state.subscribe(lambda e: fired.append(e.get("detainer_id"))
                    if e.type == EventType.DETAINED else None)

    eng.rules.detain(c, "p1")

    assert combat.is_detained(c)
    assert c.detained_by == {"p1"}
    assert fired == ["p1"]


def test_detained_creature_cannot_attack_or_block():
    eng, state = _engine()
    theirs = _creature("Theirs", "p2")   # will be detained, then try to attack
    mine = _creature("Mine", "p1")       # attacks so `theirs` can try to block
    state.add_to_battlefield(theirs)
    state.add_to_battlefield(mine)
    eng.rules.detain(theirs, "p1")

    # can't attack (RULE 701.35b) — p2's turn, p2 tries to attack with `theirs`
    state.active_player_index = 1
    state.current_step = "declare_attackers"
    assert eng._can_attack(state.player_by_id("p2"), theirs) is False

    # can't block — p1 attacks p2, `theirs` may not block
    state.active_player_index = 0
    eng._clear_combat()
    state.current_step = "declare_attackers"
    eng.declare_attackers(
        state.player_by_id("p1"),
        [{"attacker": mine, "defender": {"kind": "player", "id": "p2"}}],
    )
    assert eng.can_block(state.player_by_id("p2"), theirs, mine) is False


def test_detained_permanent_abilities_cannot_be_activated():
    eng, state = _engine()
    card = Card(id="TAP", name="Tapper", type_line="Creature — Wizard",
                is_creature=True, power=1, toughness=1,
                oracle_text="{T}: Draw a card.")
    obj = GameObject(card, owner_id="p2", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p2"
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    p2 = state.player_by_id("p2")
    ability = obj.activated_abilities[0]
    assert eng.can_activate(p2, obj, ability) is True

    eng.rules.detain(obj, "p1")
    assert eng.can_activate(p2, obj, ability) is False  # RULE 701.35b


def test_detain_expires_at_detainers_next_turn():
    eng, state = _engine()
    eng.start()  # p1 (starting player) takes turn 1
    c = _creature("C", "p2")
    state.add_to_battlefield(c)
    eng.rules.detain(c, "p1")
    assert combat.is_detained(c)

    eng.begin_turn()  # → p2's turn: not the detainer's, so it holds
    assert state.active_player.id == "p2"
    assert combat.is_detained(c)

    eng.begin_turn()  # → p1's turn: RULE 701.35b, the detain ends
    assert state.active_player.id == "p1"
    assert not combat.is_detained(c)


def test_detain_effect_up_to_two_targets():
    eng, state = _engine()
    a, b = _creature("A", "p2"), _creature("B", "p2")
    state.add_to_battlefield(a)
    state.add_to_battlefield(b)

    src_card = Card(id="LD", name="Lyev Decree", type_line="Sorcery", is_sorcery=True,
                    oracle_text="Detain up to two target creatures your opponents control.")
    src = GameObject(src_card, owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"

    from mtg_analyzer.game.effects import DetainEffect, GameContext
    eff = DetainEffect(source=src, target_kind="creature_you_dont_control",
                       count=2, optional=True)
    eff.apply(GameContext(state, eng.rules), targets=[a, b])

    assert combat.is_detained(a) and combat.is_detained(b)


def test_leaving_battlefield_clears_detain():
    eng, state = _engine()
    c = _creature("C", "p2")
    state.add_to_battlefield(c)
    eng.rules.detain(c, "p1")
    assert combat.is_detained(c)

    c.reset_as_new_object()  # RULE 400.7
    assert not combat.is_detained(c)

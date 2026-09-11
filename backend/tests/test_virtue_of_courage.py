"""Regression tests for Virtue of Courage's "whenever a source you control
deals noncombat damage to an opponent, you may exile that many cards …"
(bug report, 2026-09-04): the trigger fired for *any* damage a controlled
source dealt to *any* player (self-damage and combat damage both slipped
through, since neither "noncombat" nor "an opponent" was actually checked),
and — via `ImpulsiveDrawEffect`'s own separate default-player bug — its
effect exiled from, and granted play permission to, whoever happened to be
the *active* player at resolution time rather than Virtue of Courage's own
controller, wrong whenever it resolved off the controller's own turn.

Engine side: `game/ability_catalogue/red_spells.py`'s `_virtue_of_courage`
(now `requires_damage_to_opponent` + `filter={"combat": False}`, the same
predicate Chandra's Incinerator already established) and `game/effects/core.py`'s
`ImpulsiveDrawEffect.apply` (now reads `self.source.controller_id` instead
of defaulting to `context.active_player`).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _card(name, type_line, **kw):
    return Card(id=name, name=name, type_line=type_line, **kw)


def _engine(*player_ids):
    return GameEngine.new_game(
        [(pid, pid, []) for pid in player_ids], starting_life=20, starting_hand=0,
    )


def _battlefield_obj(state, card, controller):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _virtue(state, controller="p1"):
    card = _card("Virtue of Courage", "Enchantment")
    return _battlefield_obj(state, card, controller)


def _pinger(state, controller="p1"):
    """An arbitrary noncombat-damage source Virtue of Courage's controller
    controls — no abilities of its own, just something `deal_damage` can
    name as the ``source``."""
    card = _card("Test Pinger", "Creature — Elemental", is_creature=True, power=1, toughness=1)
    return _battlefield_obj(state, card, controller)


def _stock_library(player, cards):
    player.library.clear()
    for card in cards:
        player.library.append(GameObject(card, owner_id=player.id, zone=Zone.LIBRARY))


def test_noncombat_damage_to_an_opponent_triggers_and_exiles_from_own_library():
    eng = _engine("p1", "p2")
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    _virtue(eng.state, controller="p1")
    pinger = _pinger(eng.state, controller="p1")
    _stock_library(p1, [
        _card("Filler", "Creature", is_creature=True),
        _card("Bolt", "Instant", mana_cost_string="{R}", converted_mana_cost=1, is_instant=True),
    ])
    top_of_p1_library = p1.library[-1]

    eng.rules.deal_damage(p2, 2, source=pinger, combat=False)
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.resolve_until_stable()

    # Exiled from Virtue of Courage's *own controller's* library (p1), not
    # the damaged opponent's (p2) — and count == the damage amount (2).
    assert top_of_p1_library.zone == Zone.EXILE
    assert top_of_p1_library in p1.exile
    assert eng.state.temp_play_permission_player[top_of_p1_library.instance_id] == "p1"


def test_combat_damage_to_an_opponent_does_not_trigger():
    eng = _engine("p1", "p2")
    p2 = eng.state.player_by_id("p2")
    _virtue(eng.state, controller="p1")
    pinger = _pinger(eng.state, controller="p1")

    eng.rules.deal_damage(p2, 2, source=pinger, combat=True)
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 0


def test_noncombat_damage_to_yourself_does_not_trigger():
    eng = _engine("p1", "p2")
    p1 = eng.state.player_by_id("p1")
    _virtue(eng.state, controller="p1")
    pinger = _pinger(eng.state, controller="p1")

    eng.rules.deal_damage(p1, 2, source=pinger, combat=False)
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 0


def test_a_source_the_controller_does_not_control_does_not_trigger():
    eng = _engine("p1", "p2")
    p1 = eng.state.player_by_id("p1")
    _virtue(eng.state, controller="p1")
    opponents_pinger = _pinger(eng.state, controller="p2")

    eng.rules.deal_damage(p1, 2, source=opponents_pinger, combat=False)
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 0


def test_exile_and_permission_go_to_virtues_controller_even_off_its_controllers_turn():
    """The active player at resolution time (p2, whose turn it is) must not
    be who the exile/play-permission effect acts on — only Virtue of
    Courage's own controller (p1) should be affected."""
    eng = _engine("p1", "p2")
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    eng.begin_turn()
    if eng.state.active_player.id != "p2":
        eng.begin_turn()  # RULE 500.1: p1's turn, then p2's
    assert eng.state.active_player.id == "p2"

    _virtue(eng.state, controller="p1")
    pinger = _pinger(eng.state, controller="p1")
    _stock_library(p1, [_card("Bolt", "Instant", mana_cost_string="{R}", converted_mana_cost=1, is_instant=True)])
    _stock_library(p2, [_card("Shock", "Instant", mana_cost_string="{R}", converted_mana_cost=1, is_instant=True)])
    top_of_p1_library = p1.library[-1]
    top_of_p2_library = p2.library[-1]

    eng.rules.deal_damage(p2, 1, source=pinger, combat=False)
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.resolve_until_stable()

    assert top_of_p1_library.zone == Zone.EXILE
    assert top_of_p1_library in p1.exile
    assert eng.state.temp_play_permission_player[top_of_p1_library.instance_id] == "p1"
    # p2's library (the active player at resolution time) was untouched.
    assert top_of_p2_library.zone == Zone.LIBRARY

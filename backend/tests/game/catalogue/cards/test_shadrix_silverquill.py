"""Shadrix Silverquill resolves its modal combat trigger."""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _shadrix_card():
    return Card(id="sh", name="Shadrix Silverquill",
                type_line="Legendary Creature — Elder Dragon", is_creature=True,
                power=2, toughness=5,
                oracle_text=("Flying, double strike\nAt the beginning of combat on your "
                             "turn, you may choose two. Each mode must target a "
                             "different player.\n• Target player creates a 2/1 white and "
                             "black Inkling creature token with flying.\n• Target player "
                             "draws a card and loses 1 life.\n• Target player puts a "
                             "+1/+1 counter on each creature they control."))


def test_registered_and_binds():
    assert is_registered("Shadrix Silverquill")
    spec = _REGISTRY["shadrix silverquill"]()[0]
    spec.validate()
    assert spec.modes["choose"] == 2
    assert len(spec.modes["options"]) == 3
    assert spec.modes["options"][2][0].type == "target_player_counter_each_creature"
    src = GameObject(_shadrix_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    bind_ability(spec, src)


def test_specs_for_real_card():
    assert specs_for(_shadrix_card())


def test_mode_three_counters_each_of_target_players_creatures():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    a = GameObject(Card(id="a", name="A", type_line="Creature — Bear", is_creature=True,
                        power=2, toughness=2), owner_id="p2", zone=Zone.BATTLEFIELD)
    a.controller_id = "p2"
    b = GameObject(Card(id="b", name="B", type_line="Creature — Ox", is_creature=True,
                        power=2, toughness=2), owner_id="p2", zone=Zone.BATTLEFIELD)
    b.controller_id = "p2"
    eng.state.add_to_battlefield(a)
    eng.state.add_to_battlefield(b)
    src = GameObject(_shadrix_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    eng.state.add_to_battlefield(src)

    eng.rules._apply_effect_specs(
        [{"type": "target_player_counter_each_creature",
          "params": {"amount": 1, "kind": "+1/+1"}}],
        src, targets=[eng.state.player_by_id("p2")],
    )
    eng.resolve_until_stable()
    assert a.counters.get("+1/+1") == 1
    assert b.counters.get("+1/+1") == 1

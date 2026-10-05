"""Zimone's Hypothesis returns creatures by power parity."""

from __future__ import annotations

from mtg_analyzer.game.card_registry import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _hyp_card():
    return Card(id="zh", name="Zimone's Hypothesis", type_line="Instant", is_instant=True,
                oracle_text=("You may put a +1/+1 counter on a creature. Then choose odd "
                             "or even. Return each creature with power of the chosen "
                             "quality to its owner's hand. (Zero is even.)"))


def test_registered_and_binds():
    assert is_registered("Zimone's Hypothesis")
    spec = _REGISTRY["zimone's hypothesis"]()[0]
    spec.validate()
    assert spec.modes["choose"] == 1
    assert [o[0].params["parity"] for o in spec.modes["options"]] == ["odd", "even"]
    src = GameObject(_hyp_card(), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    bind_ability(spec, src)


def test_specs_for_real_card():
    assert specs_for(_hyp_card())


def test_even_returns_zero_and_even_power_creatures():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    st = eng.state
    def mk(name, power, owner):
        o = GameObject(Card(id=name, name=name, type_line="Creature — Bear",
                            is_creature=True, power=power, toughness=3),
                       owner_id=owner, zone=Zone.BATTLEFIELD)
        o.controller_id = owner
        st.add_to_battlefield(o)
        return o
    two = mk("Two", 2, "p1")
    three = mk("Three", 3, "p2")
    zero = mk("Zero", 0, "p2")
    src = GameObject(_hyp_card(), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"

    eng.rules._apply_effect_specs(
        [{"type": "return_creatures_by_power_parity", "params": {"parity": "even"}}], src,
    )
    eng.resolve_until_stable()
    assert two.zone == Zone.HAND
    assert zero.zone == Zone.HAND
    assert three.zone == Zone.BATTLEFIELD


def test_odd_returns_odd_power_only():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    st = eng.state
    o1 = GameObject(Card(id="a", name="A", type_line="Creature — Bear", is_creature=True,
                         power=1, toughness=1), owner_id="p1", zone=Zone.BATTLEFIELD)
    o1.controller_id = "p1"
    o2 = GameObject(Card(id="b", name="B", type_line="Creature — Ox", is_creature=True,
                         power=4, toughness=4), owner_id="p1", zone=Zone.BATTLEFIELD)
    o2.controller_id = "p1"
    st.add_to_battlefield(o1)
    st.add_to_battlefield(o2)
    src = GameObject(_hyp_card(), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    eng.rules._apply_effect_specs(
        [{"type": "return_creatures_by_power_parity", "params": {"parity": "odd"}}], src,
    )
    eng.resolve_until_stable()
    assert o1.zone == Zone.HAND
    assert o2.zone == Zone.BATTLEFIELD

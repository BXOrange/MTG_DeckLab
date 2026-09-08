"""Oversimplify replaces creatures with appropriately sized Fractals."""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _os_card():
    return Card(id="os", name="Oversimplify", type_line="Sorcery", is_sorcery=True,
                oracle_text=("Exile all creatures. Each player creates a 0/0 green and "
                             "blue Fractal creature token and puts a number of +1/+1 "
                             "counters on it equal to the total power of creatures they "
                             "controlled that were exiled this way."))


def test_registered_and_binds():
    assert is_registered("Oversimplify")
    spec = _REGISTRY["oversimplify"]()[0]
    spec.validate()
    assert spec.effects[0].type == "oversimplify"
    src = GameObject(_os_card(), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    bind_ability(spec, src)


def test_specs_for_real_card():
    assert specs_for(_os_card())


def test_exiles_all_creatures_and_makes_sized_fractals():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    st = eng.state
    def mk(name, power, owner):
        o = GameObject(Card(id=name, name=name, type_line="Creature — Bear",
                            is_creature=True, power=power, toughness=power),
                       owner_id=owner, zone=Zone.BATTLEFIELD)
        o.controller_id = owner
        st.add_to_battlefield(o)
        return o
    mk("A", 3, "p1")
    mk("B", 2, "p1")   # p1 total = 5
    mk("C", 4, "p2")   # p2 total = 4
    src = GameObject(_os_card(), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"

    eng.rules._apply_effect_specs([{"type": "oversimplify", "params": {}}], src)
    eng.resolve_until_stable()

    assert not [o for o in st.battlefield if o.is_creature and o.card.name in ("A", "B", "C")]
    fractals = [o for o in st.battlefield if o.card.name == "Fractal"]
    assert len(fractals) == 2
    by_ctrl = {o.controller_id: o for o in fractals}
    assert by_ctrl["p1"].counters.get("+1/+1") == 5
    assert by_ctrl["p2"].counters.get("+1/+1") == 4

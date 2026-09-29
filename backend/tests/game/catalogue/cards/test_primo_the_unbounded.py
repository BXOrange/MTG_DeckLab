"""Primo, the Unbounded scales counters and Fractal tokens with combat damage."""

from __future__ import annotations

from mtg_analyzer.game.card_registry import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _primo_card():
    return Card(id="primo", name="Primo, the Unbounded",
                type_line="Legendary Creature — Fractal Wolf", is_creature=True,
                power=0, toughness=0, mana_cost_string="{X}{G}{G}{U}",
                oracle_text=("Trample\nPrimo enters with twice X +1/+1 counters on it.\n"
                             "Whenever one or more creatures you control with base power 0 "
                             "deal combat damage to a player, create a 0/0 green and blue "
                             "Fractal creature token. Put a number of +1/+1 counters on it "
                             "equal to the damage dealt."))


def test_registered_and_binds():
    assert is_registered("Primo, the Unbounded")
    specs = _REGISTRY["primo, the unbounded"]()
    assert [s.effects[0].type for s in specs] == ["add_counters", "base0_combat_damage_fractal"]
    src = GameObject(_primo_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


def test_specs_for_real_card():
    assert specs_for(_primo_card())


def test_enters_with_twice_x_counters():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_life=20, starting_hand=0)
    src = GameObject(_primo_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    src.x_paid = 3
    eng.state.add_to_battlefield(src)
    eng.rules._apply_effect_specs([{"type": "add_counters", "params": {"x_multiplier": 2}}], src)
    assert src.counters.get("+1/+1", 0) == 6


def test_base_power_zero_combat_damage_makes_sized_fractal():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_life=20, starting_hand=0)
    src = GameObject(_primo_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    eng.state.add_to_battlefield(src)
    src.counters["+1/+1"] = 2  # Primo is a printed 0/0 (RULE 704.5f)
    specs = _REGISTRY["primo, the unbounded"]()
    for s in specs:
        bound = bind_ability(s, src)
        for ab in (bound if isinstance(bound, list) else [bound]):
            src.triggered_abilities.append(ab)

    def _creature(name, power):
        obj = GameObject(Card(id=name, name=name, type_line="Creature — Fractal",
                              is_creature=True, power=power, toughness=1),
                         owner_id="p1", zone=Zone.BATTLEFIELD)
        obj.controller_id = "p1"
        eng.state.add_to_battlefield(obj)
        return obj

    def _hit(contributor, amount):
        eng.state.fire_event(GameEvent(
            EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER,
            player_id="p1", target_id="p2", is_player=True,
            base_power_0_amount=amount if contributor.card.power == 0 else 0, amount=amount,
            contributor_ids=[contributor.instance_id], contributor_amounts=[amount],
        ))
        eng.resolve_until_stable()

    def _fractals():
        return [o for o in eng.state.battlefield if o.card.name == "Fractal"]

    # PAR-131: the composed per-contributor ``base_power: 0`` filter.
    _hit(_creature("Printed Two", 2), 2)
    assert _fractals() == []
    zero = _creature("Printed Zero", 0)
    zero.counters["+1/+1"] = 4
    eng.recompute_continuous_effects()
    _hit(zero, 4)
    fractals = _fractals()
    assert len(fractals) == 1
    assert fractals[0].counters.get("+1/+1", 0) == 4

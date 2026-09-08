"""Secrets of Strixhaven — playability batch, wave 100 (PAR-60).

Primo, the Unbounded — clause 1 reuses `AddCountersEffect.x_multiplier`
(Banquet Guests); clause 2 reuses `CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER`
with a new ``contributor_base_power_zero`` predicate + a
`base0_combat_damage_fractal` effect (0/0 Fractal token, counters == damage).
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.effect_binder import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone


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
    specs = _REGISTRY["primo, the unbounded"]()
    for s in specs:
        bound = bind_ability(s, src)
        for ab in (bound if isinstance(bound, list) else [bound]):
            src.triggered_abilities.append(ab)

    eng.state.fire_event(GameEvent(
        EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER,
        player_id="p1", target_id="p2", is_player=True,
        any_base_power_0=True, base_power_0_amount=4, amount=4,
        contributor_ids=[], max_power=0,
    ))
    eng.resolve_until_stable()
    fractals = [o for o in eng.state.battlefield if o.card.name == "Fractal"]
    assert len(fractals) == 1
    assert fractals[0].counters.get("+1/+1", 0) == 4

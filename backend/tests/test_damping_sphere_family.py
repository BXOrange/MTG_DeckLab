"""MEC-36 — Damping Sphere's two unscoped statics: a mana-type-override-by-
amount-produced static (any land tapped for 2+ mana produces {C} instead)
and a per-caster storm-count-scaled cost tax ("costs {1} more for each
other spell that player has cast this turn").

New primitives: `StaticAbility` layer `"mana_type_override"`, consulted
directly by `GameEngine.tap_for_mana` (`continuous.mana_type_override_for`);
`continuous.count_selector`'s new `"spells_cast_this_turn"` key, reused by
`cost_reduction`'s existing `per` vocabulary; `GameState.
spells_cast_this_turn`'s reset widened from active-player-only to every
player, every turn.

Reference: docs/implementation-state/Done_Backend.md "MEC-36" entry.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.card import Card

from tests.test_game_engine import instant, make_engine, obj_on_battlefield


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _dual_land(name="Dual Land", amount=2, color="R"):
    return Card(
        id=name, name=name, type_line="Land", is_land=True,
        oracle_text=f"{{T}}: Add {{{color}}}" * amount + ".",
    )


def _sphere_engine():
    eng = make_engine([_named("Damping Sphere")], [], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    sphere = p1.hand[0]
    bind_from_catalogue(sphere)
    eng.state.player_by_id("p1").hand.remove(sphere)
    from mtg_analyzer.models.game_object import Zone

    sphere.zone = Zone.BATTLEFIELD
    eng.state.add_to_battlefield(sphere)
    eng.recompute_continuous_effects()
    return eng, p1


def test_damping_sphere_forces_a_two_mana_tap_to_colorless():
    eng, p1 = _sphere_engine()
    land = obj_on_battlefield(eng.state, eng, _dual_land(amount=2), controller="p1")

    eng.tap_for_mana(p1, land)

    assert p1.mana_pool.pool.get("R", 0) == 0
    assert p1.mana_pool.pool.get("C", 0) == 2


def test_damping_sphere_leaves_a_single_mana_tap_alone():
    eng, p1 = _sphere_engine()
    land = obj_on_battlefield(eng.state, eng, _dual_land(amount=1), controller="p1")

    eng.tap_for_mana(p1, land)

    assert p1.mana_pool.pool.get("R", 0) == 1
    assert p1.mana_pool.pool.get("C", 0) == 0


def test_damping_sphere_taxes_each_spell_by_prior_spells_cast_this_turn():
    eng, p1 = _sphere_engine()
    shock1 = obj_on_battlefield(eng.state, eng, instant("Shock1"), controller="p1")
    shock2 = obj_on_battlefield(eng.state, eng, instant("Shock2"), controller="p1")
    eng.state.battlefield.remove(shock1)
    eng.state.battlefield.remove(shock2)
    p1.hand.extend([shock1, shock2])
    shock1.zone = shock2.zone = __import__(
        "mtg_analyzer.models.game_object", fromlist=["Zone"]
    ).Zone.HAND

    cost_before_any_cast = eng.effective_cast_cost(p1, shock1)
    assert cost_before_any_cast.converted_mana_cost == 1  # printed {R}, no tax yet

    p1.mana_pool.add_many({"R": 1})
    eng.cast_spell(p1, shock1, targets=None)
    eng.resolve_until_stable()

    cost_after_one_cast = eng.effective_cast_cost(p1, shock2)
    assert cost_after_one_cast.converted_mana_cost == 2  # {R} + {1} tax

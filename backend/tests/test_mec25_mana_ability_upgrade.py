"""Tests for MEC-25 — `effects.grant_mana_ability`'s upgrade shape.

Before this, a layer-6 "X have '{T}: Add ...'" mana grant was always a bare
repeatable ``{T}``, with no way to express a *replacement* mana ability with
its own cost — so Goldspan Dragon's real printed "Treasures you control have
'{T}, Sacrifice this artifact: Add two mana of any one color.'" could only
keep Treasure's own default one-mana version rather than upgrading it.

`grant_mana_ability`'s new ``cost`` param carries a non-``{T}``-only cost
(`continuous._apply_layer_6_ability`'s ``mana_ability_cost`` handling,
`GameObject.granted_mana_ability_upgrades`) and *replaces* a printed mana
ability whose cost has the same shape rather than adding a second one
alongside it (`mana_abilities.mana_abilities_for`'s replace-matching, via
`_cost_shape` — cost-dataclass equality with ``raw`` blanked, so "Sacrifice
this token" and "Sacrifice this artifact" still count as the same shape).

Reference: mtg_analyzer/game/effects.py (`grant_mana_ability`),
mtg_analyzer/game/continuous.py (`_apply_layer_6_ability`),
mtg_analyzer/game/mana_abilities.py (`mana_abilities_for`, `_cost_shape`),
mtg_analyzer/game/ability_catalogue.py (Goldspan Dragon), RULE 605.1a/613.7f.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.mana_abilities import mana_abilities_for
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )


def put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def goldspan_dragon():
    return Card(
        id="Goldspan Dragon", name="Goldspan Dragon", type_line="Creature — Dragon",
        is_creature=True, power=4, toughness=4,
        oracle_text=(
            "Flying, haste\n"
            "Whenever this creature attacks or becomes the target of a spell, "
            "create a Treasure token.\n"
            'Treasures you control have "{T}, Sacrifice this artifact: Add two '
            'mana of any one color."'
        ),
    )


def treasure():
    return Card(
        id="Treasure", name="Treasure", type_line="Token Artifact — Treasure",
        is_creature=False,
        oracle_text="{T}, Sacrifice this token: Add one mana of any color.",
    )


def bear():
    return Card(id="Bear", name="Bear", type_line="Creature — Bear",
                is_creature=True, power=2, toughness=2)


# ---------------------------------------------------------------------------
# The upgrade replaces the printed ability rather than stacking a second one
# ---------------------------------------------------------------------------


def test_treasure_keeps_exactly_one_mana_ability_at_the_upgraded_amount():
    eng = make_engine()
    put(eng.state, goldspan_dragon())
    t = put(eng.state, treasure())
    eng.recompute_continuous_effects()

    abilities = mana_abilities_for(t, eng.state)
    assert len(abilities) == 1
    ability = abilities[0]
    assert ability.cost.taps_self and ability.cost.sacrifice == "self"
    assert ability.options == [{"W": 2}, {"U": 2}, {"B": 2}, {"R": 2}, {"G": 2}]


def test_tapping_the_upgraded_treasure_produces_two_mana_and_sacrifices_it():
    eng = make_engine()
    put(eng.state, goldspan_dragon())
    t = put(eng.state, treasure())
    eng.recompute_continuous_effects()

    player = eng.state.player_by_id("p1")
    produced = eng.tap_for_mana(player, t, option_index=0)
    assert produced == {"W": 2}
    assert t not in eng.state.battlefield  # RULE 605.1a's own sacrifice cost


def test_a_non_treasure_permanent_is_unaffected():
    eng = make_engine()
    put(eng.state, goldspan_dragon())
    a_bear = put(eng.state, bear())
    eng.recompute_continuous_effects()

    assert mana_abilities_for(a_bear, eng.state) == []


def test_the_upgrade_disappears_when_goldspan_dragon_leaves():
    eng = make_engine()
    dragon = put(eng.state, goldspan_dragon())
    t = put(eng.state, treasure())
    eng.recompute_continuous_effects()
    assert len(mana_abilities_for(t, eng.state)) == 1

    eng.state.remove_from_battlefield(dragon)
    eng.recompute_continuous_effects()

    abilities = mana_abilities_for(t, eng.state)
    assert len(abilities) == 1
    # Back to Treasure's own printed one-mana version — the layer-6 grant
    # disappeared on its own (RULE 613.6), no separate removal code needed.
    assert abilities[0].options == [{"W": 1}, {"U": 1}, {"B": 1}, {"R": 1}, {"G": 1}]


# ---------------------------------------------------------------------------
# Real card end-to-end
# ---------------------------------------------------------------------------


def test_goldspan_dragon_is_registered_with_the_static_grant():
    from mtg_analyzer.game.ability_catalogue import specs_for

    specs = specs_for(goldspan_dragon())
    static_specs = [s for s in specs if s.ability_kind == "static"]
    assert len(static_specs) == 1
    assert static_specs[0].effects[0].type == "grant_mana_ability"
    assert static_specs[0].effects[0].params.get("cost")

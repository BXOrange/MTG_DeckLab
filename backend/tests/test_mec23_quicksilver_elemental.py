"""Tests for MEC-23 — Quicksilver Elemental, the one card the Vivi B4 batch
(2026-08-10) left open. Two new primitives:

  * `effects.GainActivatedAbilitiesOfTargetEffect`
    (``"gain_target_activated_abilities"``) — the resolve-time, single-target
    sibling of MEC-21's standing layer-6 `grant_borrowed_activated_ability`
    (Agatha's Soul Cauldron): snapshots ``target.activated_abilities`` once,
    at resolution, onto a turn-scoped `GameObject.
    temp_granted_activated_abilities` field (cleared at cleanup, RULE
    514.2) rather than re-deriving live off a standing static every
    `continuous.recompute` pass.
  * `continuous.any_color_for_activation` gained ``from_color``/
    ``self_only`` params — Agatha's own grant lets any of the five colors
    pay any colored pip for any creature the controller controls;
    Quicksilver's only lets **blue** mana substitute (`ManaPool._solve`'s
    matching single-color branch), and only for its own abilities.

Reference: mtg_analyzer/game/effects/core.py (`GainActivatedAbilitiesOfTargetEffect`,
`grant_any_color_for_activation`), mtg_analyzer/game/continuous.py
(`any_color_for_activation`, `_retarget_effect_source`),
mtg_analyzer/models/mana_pool.py (`ManaPool._solve`),
mtg_analyzer/game/ability_catalogue.py (Quicksilver Elemental),
RULE 113.7c/605.1a/613.7f.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )


def put(state, card, controller="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(card, owner_id=controller, zone=zone)
    obj.summoning_sick = False
    if zone == Zone.BATTLEFIELD:
        state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def quicksilver_elemental():
    return Card(
        id="Quicksilver Elemental", name="Quicksilver Elemental",
        type_line="Creature — Elemental", is_creature=True, power=3, toughness=4,
        mana_cost_string="{3}{U}{U}",
        oracle_text=(
            "{U}: This creature gains all activated abilities of target creature "
            "until end of turn. (If any of the abilities use that creature's name, "
            "use this creature's name instead.)\n"
            "You may spend blue mana as though it were mana of any color to pay the "
            "activation costs of this creature's abilities."
        ),
    )


def pinger():
    return Card(
        id="Prodigal Pyromancer", name="Prodigal Pyromancer",
        type_line="Creature — Human Wizard", is_creature=True, power=1, toughness=1,
        oracle_text="{T}: This creature deals 1 damage to any target.",
    )


def red_pinger():
    return Card(
        id="Red Guy", name="Red Guy", type_line="Creature — Human Wizard",
        is_creature=True, power=1, toughness=1,
        oracle_text="{R}: This creature deals 1 damage to any target.",
    )


# ---------------------------------------------------------------------------
# Clause 1 — resolve-time, turn-scoped ability borrowing
# ---------------------------------------------------------------------------


def test_activating_the_ability_copies_the_targets_activated_abilities():
    eng = make_engine()
    elemental = put(eng.state, quicksilver_elemental())
    target = put(eng.state, pinger(), controller="p2")

    p1 = eng.state.player_by_id("p1")
    p1.mana_pool.add("U", 1)
    eng.activate_ability(p1, elemental, ability_index=0, targets=[target])
    eng.resolve_until_stable()

    assert len(elemental.granted_activated_abilities) == 1
    borrowed = elemental.granted_activated_abilities[0]
    assert borrowed.source is elemental  # RULE 113.7c — applies as the grantee's own
    assert borrowed.cost.raw == target.activated_abilities[0].cost.raw


def test_activating_the_borrowed_ability_taps_and_sources_from_the_elemental():
    eng = make_engine()
    elemental = put(eng.state, quicksilver_elemental())
    target = put(eng.state, pinger(), controller="p1")
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")

    p1.mana_pool.add("U", 1)
    eng.activate_ability(p1, elemental, ability_index=0, targets=[target])
    eng.resolve_until_stable()

    life_before = p2.life
    borrowed_index = len(elemental.activated_abilities)
    eng.activate_ability(p1, elemental, ability_index=borrowed_index, targets=[p2], tap_choices=[])
    eng.resolve_until_stable()

    assert p2.life == life_before - 1
    assert elemental.tapped
    assert not target.tapped  # the original ability's own source is untouched


def test_the_grant_is_cleared_at_cleanup():
    eng = make_engine()
    elemental = put(eng.state, quicksilver_elemental())
    target = put(eng.state, pinger(), controller="p2")
    p1 = eng.state.player_by_id("p1")

    p1.mana_pool.add("U", 1)
    eng.activate_ability(p1, elemental, ability_index=0, targets=[target])
    eng.resolve_until_stable()
    assert len(elemental.granted_activated_abilities) == 1

    eng._step_cleanup()
    assert elemental.granted_activated_abilities == []


def test_a_creature_with_no_activated_abilities_grants_nothing():
    eng = make_engine()
    elemental = put(eng.state, quicksilver_elemental())
    vanilla = put(eng.state, Card(id="Bear", name="Bear", type_line="Creature — Bear",
                                   is_creature=True, power=2, toughness=2), controller="p2")
    p1 = eng.state.player_by_id("p1")

    p1.mana_pool.add("U", 1)
    eng.activate_ability(p1, elemental, ability_index=0, targets=[vanilla])
    eng.resolve_until_stable()

    assert elemental.granted_activated_abilities == []


# ---------------------------------------------------------------------------
# Clause 2 — blue-only wildcard, self-scoped
# ---------------------------------------------------------------------------


def test_blue_mana_pays_a_borrowed_red_activation_cost():
    eng = make_engine()
    elemental = put(eng.state, quicksilver_elemental())
    target = put(eng.state, red_pinger(), controller="p2")
    p1 = eng.state.player_by_id("p1")

    p1.mana_pool.add("U", 2)
    eng.activate_ability(p1, elemental, ability_index=0, targets=[target])
    eng.resolve_until_stable()

    borrowed_index = len(elemental.activated_abilities)
    borrowed = elemental.granted_activated_abilities[0]
    assert eng.can_activate(p1, elemental, borrowed, tap_choices=[])  # only blue left in pool
    eng.activate_ability(p1, elemental, ability_index=borrowed_index, targets=[p1], tap_choices=[])
    eng.resolve_until_stable()  # doesn't raise — the {R} cost was paid with blue


def test_non_blue_mana_does_not_pay_the_borrowed_red_activation_cost():
    eng = make_engine()
    elemental = put(eng.state, quicksilver_elemental())
    target = put(eng.state, red_pinger(), controller="p2")
    p1 = eng.state.player_by_id("p1")

    p1.mana_pool.add("U", 1)
    eng.activate_ability(p1, elemental, ability_index=0, targets=[target])
    eng.resolve_until_stable()

    borrowed = elemental.granted_activated_abilities[0]
    p1.mana_pool.add("G", 1)  # green in the pool, but the wildcard only covers blue
    assert eng.can_activate(p1, elemental, borrowed, tap_choices=[]) is False


def test_the_wildcard_does_not_apply_to_another_creatures_own_ability():
    eng = make_engine()
    put(eng.state, quicksilver_elemental())
    other = put(eng.state, red_pinger(), controller="p1")
    eng.recompute_continuous_effects()

    from mtg_analyzer.game import continuous
    p1 = eng.state.player_by_id("p1")
    assert continuous.any_color_for_activation(eng.state, p1, other) is None


def test_wildcard_token_is_the_specific_color_not_the_unrestricted_form():
    eng = make_engine()
    elemental = put(eng.state, quicksilver_elemental())
    eng.recompute_continuous_effects()

    from mtg_analyzer.game import continuous
    p1 = eng.state.player_by_id("p1")
    assert continuous.any_color_for_activation(eng.state, p1, elemental) == "U"


# ---------------------------------------------------------------------------
# Real card end-to-end
# ---------------------------------------------------------------------------


def test_quicksilver_elemental_is_registered_with_both_pieces():
    from mtg_analyzer.game.ability_catalogue import specs_for

    specs = specs_for(quicksilver_elemental())
    kinds = [(s.ability_kind, s.effects[0].type) for s in specs]
    assert ("activated", "gain_target_activated_abilities") in kinds
    assert ("static", "grant_any_color_for_activation") in kinds
    static = next(s for s in specs if s.ability_kind == "static")
    assert static.effects[0].params.get("from_color") == "U"
    assert static.effects[0].params.get("self_only") is True

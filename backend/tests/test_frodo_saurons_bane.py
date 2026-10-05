"""Frodo, Sauron's Bane: two activated abilities that each conditionally
transform the permanent's own type line, base power/toughness and ability
set (RULE 205.1b/613.6) — a two-step standing conditional static, gated on
a plain custom-kind progress counter (``frodo_stage``), rather than the
"genuine two-stage state machine … unlike anything else cached" the
BACKLOG previously read it as.

New primitives this closes with:

* `ActivationCost.activation_condition` settable directly from a
  hand-authored `AbilitySpec.cost` dict (`game/costs.py`'s
  `parse_activation_cost`), not just via the oracle parser's marker-strip
  path — "if Frodo is a Citizen/Scout" gates each ability's own legality.
* `ConditionalEffect`'s ``ring_tempted_at_most`` condition key, the upper-
  bound mirror of the existing ``ring_tempted_at_least`` — together
  expressing "…if tempted 4+ times. Otherwise, …" as two independently
  gated effects.
* `continuous._build_grant_effect` (`grant_triggered_ability`'s own
  ``grant_effects`` list) honouring an optional per-entry ``condition``,
  so a *granted* ability can have an internal if/else the same way a
  printed one already can via `EffectSpec.condition`.
* `LoseGameTriggerDamagedPlayerEffect` — "that player loses the game",
  the player-flavoured mirror of `ExileTriggerDamagedCreatureEffect`'s
  "that creature" pronoun off the firing `DAMAGE` event.

Reference: mtg_analyzer/game/{card_registry,effects,continuous,costs}.py.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _frodo_card():
    return Card(
        id="Frodo, Sauron's Bane", name="Frodo, Sauron's Bane",
        type_line="Legendary Creature — Halfling Citizen",
        mana_cost_string="{W}", is_creature=True, power=1, toughness=2,
        oracle_text=(
            "{W/B}{W/B}: If Frodo is a Citizen, it becomes a Halfling Scout "
            "with base power and toughness 2/3 and lifelink.\n"
            "{B}{B}{B}: If Frodo is a Scout, it becomes a Halfling Rogue "
            "with \"Whenever this creature deals combat damage to a player, "
            "that player loses the game if the Ring has tempted you four or "
            "more times this game. Otherwise, the Ring tempts you.\""
        ),
    )


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj




def test_starts_as_a_1_2_halfling_citizen():
    eng = _engine()
    frodo = _bf(eng.state, _frodo_card())
    eng.recompute_continuous_effects()
    assert frodo.power == 1 and frodo.toughness == 2
    assert not frodo.card.type_line.endswith("Scout")
    assert "lifelink" not in frodo.granted_keywords


def test_second_ability_illegal_before_the_first():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    frodo = _bf(eng.state, _frodo_card())
    p1.mana_pool.add("B", 3)
    rogue_ability = frodo.activated_abilities[1]
    assert not eng.can_activate(p1, frodo, rogue_ability)


def test_first_activation_becomes_a_2_3_lifelink_scout():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    frodo = _bf(eng.state, _frodo_card())
    p1.mana_pool.add("W", 2)
    scout_ability = frodo.activated_abilities[0]
    assert eng.can_activate(p1, frodo, scout_ability)
    eng.activate_ability(p1, frodo, 0)
    eng.rules.resolve_top_of_stack()
    eng.recompute_continuous_effects()
    assert frodo.power == 2 and frodo.toughness == 3
    assert "Scout" in frodo._derived_subtypes
    assert "lifelink" in frodo.granted_keywords
    # Not activatable a second time — RULE-shaped "no skipping/repeating".
    assert not eng.can_activate(p1, frodo, scout_ability)


def test_second_activation_becomes_a_rogue_that_keeps_2_3():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    frodo = _bf(eng.state, _frodo_card())
    p1.mana_pool.add("W", 2)
    p1.mana_pool.add("B", 3)
    eng.activate_ability(p1, frodo, 0)
    eng.rules.resolve_top_of_stack()
    eng.recompute_continuous_effects()
    rogue_ability = frodo.activated_abilities[1]
    assert eng.can_activate(p1, frodo, rogue_ability)
    eng.activate_ability(p1, frodo, 1)
    eng.rules.resolve_top_of_stack()
    eng.recompute_continuous_effects()
    assert "Rogue" in frodo._derived_subtypes
    # The Rogue static never restates a P/T — RULE 613.7 timestamp
    # layering keeps the still-active Scout static's own 2/3 underneath.
    assert frodo.power == 2 and frodo.toughness == 3
    assert len(frodo.granted_triggered_abilities) == 1


def test_rogue_trigger_tempts_the_ring_below_four_temptations():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    frodo = _bf(eng.state, _frodo_card())
    p1.mana_pool.add("W", 2)
    p1.mana_pool.add("B", 3)
    eng.activate_ability(p1, frodo, 0)
    eng.rules.resolve_top_of_stack()
    eng.activate_ability(p1, frodo, 1)
    eng.rules.resolve_top_of_stack()
    eng.recompute_continuous_effects()
    assert p1.ring_level == 0
    eng.rules.deal_damage(p2, 1, source=frodo, combat=True)
    eng.resolve_until_stable()
    assert p1.ring_level == 1
    assert p2.has_lost is False


def test_rogue_trigger_kills_the_defender_at_four_or_more_temptations():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    frodo = _bf(eng.state, _frodo_card())
    p1.mana_pool.add("W", 2)
    p1.mana_pool.add("B", 3)
    eng.activate_ability(p1, frodo, 0)
    eng.rules.resolve_top_of_stack()
    eng.activate_ability(p1, frodo, 1)
    eng.rules.resolve_top_of_stack()
    eng.recompute_continuous_effects()
    p1.ring_level = 4
    eng.rules.deal_damage(p2, 1, source=frodo, combat=True)
    eng.resolve_until_stable()
    assert p1.ring_level == 4  # unchanged — the "otherwise" branch didn't fire
    assert p2.has_lost is True

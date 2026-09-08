"""Tests for RULE 115.1a "N target(s)"/"up to N target(s)" generalized to
N>=2 — a real multi-target choice, as opposed to the N=1-only "up to one
target" case (`test_optional_targets.py`).

Scoped to a **single** targeting effect wanting N targets (not several
*different* targeting effects on one spell) — `game/targeting.py`'s
`TargetSpec.count` docstring explains why: a stack item's resolved
``targets`` list is shared by every effect on it, so this feature only
covers "one effect, N targets" (all real cards found — Curtains' Call,
Force of Vigor, Volcanic Salvo — are exactly this shape). Wired up for
`destroy`/`exile`/`damage` only; the other targeting effect families
(return_to_hand/tap/add_counters/return_from_graveyard) stay N=1-only until
a real card drives extending them too (see `test_optional_targets.py`).

Mirrors `test_optional_targets.py`'s fixture pattern and parser-recognition-
then-engine-drive split.
"""

import pytest

from mtg_analyzer.game.effects.core import DealDamageEffect, DestroyEffect, ExileEffect
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import all_requirements_satisfiable, requirements_with_targets
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.mana_cost import ManaCost
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def instant(name, cost="{0}", oracle_text=""):
    return Card(
        id=name, name=name, type_line="Instant", mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost if cost else 0,
        is_instant=True, oracle_text=oracle_text,
    )


def creature(name="Grizzly Bears"):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
                power=2, toughness=2)


def two_player_engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", [instant("filler")] * 5), ("p2", "Bob", [instant("f")] * 5)],
        starting_hand=0,
    )
    return eng, eng.state.player_by_id("p1"), eng.state.player_by_id("p2")


def give_spell(eng, player, card, effects):
    obj = GameObject(card, owner_id=player.id, zone=Zone.HAND)
    obj.spell_effects = effects
    for e in effects:
        e.source = obj
    player.hand.append(obj)
    return obj


def cast_action_for(eng, player, obj):
    for a in eng.legal_actions(player):
        if a.get("type") == "cast_spell" and a["instance_id"] == obj.instance_id:
            return a
    return None


# ---------------------------------------------------------------------------
# PARSER RECOGNITION
# ---------------------------------------------------------------------------


def test_mandatory_two_targets_recognized_for_destroy():
    # Curtains' Call-shaped: "Destroy two target creatures."
    (spec,) = parse_effect_body("destroy 2 target creatures")
    assert spec.type == "destroy"
    assert spec.params == {"target_kind": "creature", "count": 2}
    assert "optional" not in spec.params


def test_optional_up_to_two_recognized_for_destroy_with_and_or_types():
    # Force of Vigor-shaped: "Destroy up to two target artifacts and/or
    # enchantments."
    (spec,) = parse_effect_body("destroy up to 2 target artifacts and/or enchantments")
    assert spec.type == "destroy"
    assert spec.params == {"target_kind": "permanent", "count": 2, "optional": True}


def test_optional_up_to_three_recognized_for_exile():
    (spec,) = parse_effect_body("exile up to 3 target creatures")
    assert spec.type == "exile"
    assert spec.params == {"target_kind": "creature", "count": 3, "optional": True}


def test_mandatory_two_targets_recognized_for_exile():
    (spec,) = parse_effect_body("exile 2 target permanents")
    assert spec.type == "exile"
    assert spec.params == {"target_kind": "permanent", "count": 2}


def test_damage_to_each_of_up_to_n_targets():
    # Volcanic Salvo-shaped: "~ deals 6 damage to each of up to two target
    # creatures and/or planeswalkers." — the full amount hits *each* target.
    (spec,) = parse_effect_body(
        "deals 6 damage to each of up to 2 target creatures and/or planeswalkers"
    )
    assert spec.type == "damage"
    assert spec.params == {"amount": 6, "target_kind": "any", "count": 2, "optional": True}


def test_damage_to_each_of_n_targets_mandatory():
    (spec,) = parse_effect_body("deals 3 damage to each of 2 target creatures")
    assert spec.type == "damage"
    assert spec.params == {"amount": 3, "target_kind": "creature", "count": 2}


def test_count_of_one_is_not_this_grammar():
    # N=1 stays the existing singular handler's job — this grammar requires
    # count >= 2, so "destroy one target creature" falls through unclaimed
    # here (it isn't real card phrasing anyway; real N=1 is a bare "target").
    assert parse_effect_body("destroy 1 target creature") is None


def test_unrecognized_plural_target_phrase_stays_unclaimed():
    assert parse_effect_body("destroy 2 target spells") is None


# ---------------------------------------------------------------------------
# EFFECT CLASSES: count propagates to TargetSpec
# ---------------------------------------------------------------------------


def test_count_reaches_target_spec():
    assert DestroyEffect(count=2).target_spec.count == 2
    assert ExileEffect(count=3, optional=True).target_spec.count == 3
    assert DealDamageEffect(6, count=2, optional=True).target_spec.count == 2
    # Default stays 1, unaffected.
    assert DestroyEffect().target_spec.count == 1


# ---------------------------------------------------------------------------
# ENGINE: RULE 601.2c castability — mandatory N needs >= N legal targets
# ---------------------------------------------------------------------------


def test_mandatory_two_targets_locks_with_only_one_legal_target():
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    obj = give_spell(eng, p1, instant("Double Murder"), [DestroyEffect(count=2)])
    action = cast_action_for(eng, p1, obj)
    assert action.get("locked") is True


def test_mandatory_two_targets_castable_with_two_legal_targets():
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    wolf = GameObject(creature("Wolf"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    eng.state.add_to_battlefield(wolf)
    obj = give_spell(eng, p1, instant("Double Murder"), [DestroyEffect(count=2)])
    action = cast_action_for(eng, p1, obj)
    assert action.get("locked") is None


def test_optional_up_to_two_never_locks_even_with_an_empty_board():
    eng, p1, p2 = two_player_engine()
    obj = give_spell(eng, p1, instant("Maybe Double Murder"), [DestroyEffect(count=2, optional=True)])
    action = cast_action_for(eng, p1, obj)
    assert action.get("requires_target") is True
    assert action.get("locked") is None


# ---------------------------------------------------------------------------
# ENGINE: resolution applies to exactly the chosen (up to) N targets
# ---------------------------------------------------------------------------


def test_choosing_two_targets_destroys_both():
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    wolf = GameObject(creature("Wolf"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    eng.state.add_to_battlefield(wolf)
    obj = give_spell(eng, p1, instant("Double Murder"), [DestroyEffect(count=2)])
    eng.cast_spell(p1, obj, targets=[bear, wolf])
    eng.rules.resolve_top_of_stack()
    assert bear.zone == Zone.GRAVEYARD
    assert wolf.zone == Zone.GRAVEYARD


def test_choosing_fewer_than_the_optional_max_only_affects_those_chosen():
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    wolf = GameObject(creature("Wolf"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    eng.state.add_to_battlefield(wolf)
    obj = give_spell(eng, p1, instant("Maybe Double Murder"), [DestroyEffect(count=2, optional=True)])
    eng.cast_spell(p1, obj, targets=[bear])  # only one chosen, though up to 2 allowed
    eng.rules.resolve_top_of_stack()
    assert bear.zone == Zone.GRAVEYARD
    assert wolf.zone == Zone.BATTLEFIELD  # untouched


def test_declining_all_optional_targets_is_a_legal_no_op():
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    obj = give_spell(eng, p1, instant("Maybe Double Murder"), [DestroyEffect(count=2, optional=True)])
    eng.cast_spell(p1, obj, targets=None)
    eng.rules.resolve_top_of_stack()
    assert bear.zone == Zone.BATTLEFIELD


def test_damage_effect_applies_full_amount_to_each_of_n_targets():
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    wolf = GameObject(creature("Wolf"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    eng.state.add_to_battlefield(wolf)
    obj = give_spell(eng, p1, instant("Double Bolt"), [DealDamageEffect(6, count=2)])
    eng.cast_spell(p1, obj, targets=[bear, wolf])
    eng.rules.resolve_top_of_stack()
    eng.rules.check_state_based_actions()
    assert bear not in eng.state.battlefield  # 6 damage each, not divided
    assert wolf not in eng.state.battlefield


def test_a_shared_targets_list_longer_than_count_is_not_over_consumed():
    # See TargetSpec.count's docstring: a stack item's targets list can be
    # shared by more than this one effect — DestroyEffect(count=2) must
    # only take its own first two, not silently consume a third meant for
    # something else sharing the same cast.
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    wolf = GameObject(creature("Wolf"), owner_id="p2", zone=Zone.BATTLEFIELD)
    fox = GameObject(creature("Fox"), owner_id="p2", zone=Zone.BATTLEFIELD)
    for o in (bear, wolf, fox):
        eng.state.add_to_battlefield(o)
    obj = give_spell(eng, p1, instant("Double Murder"), [DestroyEffect(count=2)])
    eng.cast_spell(p1, obj, targets=[bear, wolf, fox])
    eng.rules.resolve_top_of_stack()
    assert bear.zone == Zone.GRAVEYARD
    assert wolf.zone == Zone.GRAVEYARD
    assert fox.zone == Zone.BATTLEFIELD  # not consumed


# ---------------------------------------------------------------------------
# END-TO-END: real card oracle text -> parse -> bind -> cast -> resolve
# ---------------------------------------------------------------------------


def test_curtains_call_end_to_end():
    card = instant("Curtains' Call", cost="{3}{B}{B}",
                    oracle_text="Destroy two target creatures.")
    result = parse_oracle(card)
    assert result.coverage == MODELED

    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    wolf = GameObject(creature("Wolf"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    eng.state.add_to_battlefield(wolf)

    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)

    requirements = requirements_with_targets(eng.state, "p1", obj)
    assert len(requirements) == 1
    assert requirements[0]["count"] == 2
    assert all_requirements_satisfiable(requirements)

    p1.mana_pool.add_many({"B": 2, "C": 3})
    eng.cast_spell(p1, obj, targets=[bear, wolf])
    eng.rules.resolve_top_of_stack()
    assert bear.zone == Zone.GRAVEYARD
    assert wolf.zone == Zone.GRAVEYARD


def test_force_of_vigor_end_to_end():
    card = instant("Force of Vigor", cost="{3}{G}{G}",
                    oracle_text="Destroy up to two target artifacts and/or enchantments.")
    result = parse_oracle(card)
    assert result.coverage == MODELED

    eng, p1, p2 = two_player_engine()
    artifact = GameObject(
        Card(id="Sol Ring", name="Sol Ring", type_line="Artifact"),
        owner_id="p2", zone=Zone.BATTLEFIELD,
    )
    eng.state.add_to_battlefield(artifact)

    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)

    # Never locked even with only one legal target (optional, up to two).
    requirements = requirements_with_targets(eng.state, "p1", obj)
    assert all_requirements_satisfiable(requirements)

    p1.mana_pool.add_many({"G": 2, "C": 3})
    eng.cast_spell(p1, obj, targets=[artifact])
    eng.rules.resolve_top_of_stack()
    assert artifact.zone == Zone.GRAVEYARD

"""Tests for the cross-target "controlled by different players" constraint
(RULE 115.1a's N>=2 generalization, `targeting.TargetSpec.
distinct_controllers`) — Run Away Together ("choose two target creatures
controlled by different players")/Protector of the Wastes ("exile up to two
target artifacts and/or enchantments controlled by different players").

Unlike every other `TargetSpec` filter (checked per-candidate,
`_creature_matches_filter`-style), this one constrains the *relationship*
between the targets chosen for one requirement, so it's enforced at
offer/pick time across the N rounds of `gameBoardView.js`'s
`expandMultiTargetRequirements`, not inside the resolving effect itself
(which never sees anything but a final, already-legal target list) — see
`targeting.TargetSpec.distinct_controllers`'s docstring for the full
architecture note.

Mirrors `test_multi_target.py`'s fixture pattern and parser-recognition-
then-engine-drive split.
"""

from mtg_analyzer.game.effects.core import DestroyEffect, ExileEffect, ReturnToHandEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import legal_targets, requirements_with_targets, TargetSpec
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def instant(name, cost="{0}"):
    return Card(
        id=name, name=name, type_line="Instant", mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost if cost else 0,
        is_instant=True,
    )


def creature(name="Grizzly Bears", controller=None):
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


# ---------------------------------------------------------------------------
# PARSER RECOGNITION (single-sentence "destroy/exile N target X controlled
# by different players" — Protector of the Wastes-shaped)
# ---------------------------------------------------------------------------


def test_exile_up_to_two_controlled_by_different_players_is_recognized():
    # Protector of the Wastes-shaped.
    (spec,) = parse_effect_body(
        "exile up to 2 target artifacts and/or enchantments controlled by different players"
    )
    assert spec.type == "exile"
    assert spec.params == {
        "target_kind": "permanent", "count": 2, "optional": True, "distinct_controllers": True,
    }


def test_destroy_two_target_creatures_controlled_by_different_controllers_is_recognized():
    (spec,) = parse_effect_body("destroy 2 target creatures controlled by different controllers")
    assert spec.type == "destroy"
    assert spec.params == {"target_kind": "creature", "count": 2, "distinct_controllers": True}


def test_plain_multi_target_clause_has_no_distinct_controllers_key():
    # Backward compatibility: no trailing clause -> no new key at all.
    (spec,) = parse_effect_body("destroy 2 target creatures")
    assert "distinct_controllers" not in spec.params


# ---------------------------------------------------------------------------
# EFFECT CLASSES: the param reaches TargetSpec
# ---------------------------------------------------------------------------


def test_distinct_controllers_reaches_target_spec():
    assert DestroyEffect(count=2, distinct_controllers=True).target_spec.distinct_controllers is True
    assert ExileEffect(count=2, distinct_controllers=True).target_spec.distinct_controllers is True
    assert ReturnToHandEffect(count=2, distinct_controllers=True).target_spec.distinct_controllers is True
    # Default stays False, unaffected.
    assert DestroyEffect(count=2).target_spec.distinct_controllers is False


# ---------------------------------------------------------------------------
# TARGETING: legal_targets carries controller_id; requirements_with_targets
# surfaces the flag for the frontend's per-round exclusion.
# ---------------------------------------------------------------------------


def test_legal_targets_carries_controller_id_for_permanent_kind():
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    options = legal_targets(eng.state, "p1", TargetSpec(kind="creature"))
    assert options == [{"instance_id": bear.instance_id, "name": "Bear", "controller_id": "p2"}]


def test_requirements_with_targets_surfaces_distinct_controllers_flag():
    eng, p1, p2 = two_player_engine()
    obj = give_spell(
        eng, p1, instant("Run Away Together"),
        [ReturnToHandEffect(target_kind="creature", count=2, distinct_controllers=True)],
    )
    (req,) = requirements_with_targets(eng.state, "p1", obj)
    assert req["distinct_controllers"] is True


def test_requirements_with_targets_defaults_flag_false():
    eng, p1, p2 = two_player_engine()
    obj = give_spell(eng, p1, instant("Double Murder"), [DestroyEffect(count=2)])
    (req,) = requirements_with_targets(eng.state, "p1", obj)
    assert req["distinct_controllers"] is False


# ---------------------------------------------------------------------------
# ENGINE: resolution still just applies to whatever the caller submits —
# the constraint is an offer/pick-time concern, not a resolve-time one.
# ---------------------------------------------------------------------------


def test_run_away_together_shaped_engine_resolution():
    eng, p1, p2 = two_player_engine()
    mine = GameObject(creature("Mine"), owner_id="p1", zone=Zone.BATTLEFIELD)
    theirs = GameObject(creature("Theirs"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(mine)
    eng.state.add_to_battlefield(theirs)
    obj = give_spell(
        eng, p1, instant("Run Away Together"),
        [ReturnToHandEffect(target_kind="creature", count=2, distinct_controllers=True)],
    )
    eng.cast_spell(p1, obj, targets=[mine, theirs])
    eng.rules.resolve_top_of_stack()
    assert mine.zone == Zone.HAND
    assert theirs.zone == Zone.HAND

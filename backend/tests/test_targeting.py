"""Tests for target requirements + valid-target gating (RULE 115 / 601.2c).

A spell that needs a target must not be offered as castable when the board
has no legal target — it is offered *locked* instead, and casting it is
rejected server-side.
"""

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.mana_cost import ManaCost
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.effects import (
    CounterSpellEffect,
    DealDamageEffect,
    DestroyEffect,
    DrawCardEffect,
)
from mtg_analyzer.game import targeting


def instant(name, cost="{0}", **flags):
    return Card(
        id=name,
        name=name,
        type_line="Instant",
        mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost if cost else 0,
        is_instant=True,
        **flags,
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
    """Put a castable (free) instant with ``effects`` into ``player``'s hand."""
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


# --- Representation: which effects target vs. act globally ------------------


def test_targeting_effects_declare_a_target_spec():
    assert DealDamageEffect(3).target_spec.kind == "any"
    assert DestroyEffect().target_spec.kind == "permanent"
    assert CounterSpellEffect().target_spec.kind == "spell"


def test_global_effects_have_no_target_spec():
    assert DrawCardEffect(1).target_spec is None


def test_spell_target_specs_gathers_from_effects():
    eng, p1, _ = two_player_engine()
    obj = give_spell(eng, p1, instant("Murder"), [DestroyEffect()])
    specs = targeting.spell_target_specs(obj)
    assert [s.kind for s in specs] == ["permanent"]


# --- Legal target computation from the game state --------------------------


def test_creature_target_lists_only_creatures_on_battlefield():
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    spec = DestroyEffect(target_kind="creature").target_spec
    opts = targeting.legal_targets(eng.state, p1.id, spec)
    assert [o["name"] for o in opts] == ["Bear"]


def test_any_target_includes_players_and_creatures():
    eng, p1, p2 = two_player_engine()
    spec = DealDamageEffect(3).target_spec
    opts = targeting.legal_targets(eng.state, p1.id, spec)
    # Both players are legal "any" targets even with an empty battlefield.
    assert {o.get("player_id") for o in opts if "player_id" in o} == {"p1", "p2"}


def test_spell_target_reads_the_stack():
    eng, p1, p2 = two_player_engine()
    spec = CounterSpellEffect().target_spec
    assert targeting.legal_targets(eng.state, p1.id, spec) == []  # empty stack


# --- Locking: no legal target -> offered locked, not castable ---------------


def test_destroy_with_empty_board_is_locked():
    eng, p1, _ = two_player_engine()
    obj = give_spell(eng, p1, instant("Murder"), [DestroyEffect()])
    action = cast_action_for(eng, p1, obj)
    assert action is not None and action.get("requires_target")
    assert action.get("locked") is True
    assert action.get("lock_reason")


def test_destroy_with_a_creature_present_is_unlocked_with_options():
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    obj = give_spell(eng, p1, instant("Murder"), [DestroyEffect()])
    action = cast_action_for(eng, p1, obj)
    assert action.get("locked") is None
    names = {t["name"] for req in action["targets"] for t in req["options"]}
    assert "Bear" in names


def test_counter_with_empty_stack_is_locked():
    eng, p1, _ = two_player_engine()
    obj = give_spell(eng, p1, instant("Counterspell"), [CounterSpellEffect()])
    action = cast_action_for(eng, p1, obj)
    assert action.get("locked") is True


def test_damage_is_never_locked_a_player_is_always_a_target():
    eng, p1, _ = two_player_engine()
    obj = give_spell(eng, p1, instant("Lightning Bolt"), [DealDamageEffect(3)])
    action = cast_action_for(eng, p1, obj)
    assert action.get("requires_target") is True
    assert action.get("locked") is None


def test_global_spell_is_not_a_target_action():
    eng, p1, _ = two_player_engine()
    obj = give_spell(eng, p1, instant("Divination"), [DrawCardEffect(2)])
    action = cast_action_for(eng, p1, obj)
    assert action.get("requires_target") is None
    assert action.get("locked") is None


# --- Server-side enforcement (RULE 601.2c) ---------------------------------


def test_casting_a_targetless_spell_is_rejected():
    eng, p1, _ = two_player_engine()
    obj = give_spell(eng, p1, instant("Murder"), [DestroyEffect()])
    assert not eng.has_legal_targets(p1, obj)
    with pytest.raises(ValueError, match="no legal target"):
        eng.cast_spell(p1, obj)


def test_casting_is_allowed_once_a_target_exists():
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    obj = give_spell(eng, p1, instant("Murder"), [DestroyEffect()])
    assert eng.has_legal_targets(p1, obj)
    item = eng.cast_spell(p1, obj, targets=[bear])
    assert item.obj is obj  # made it onto the stack

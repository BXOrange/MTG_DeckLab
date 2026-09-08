"""Tests for target requirements + valid-target gating (RULE 115 / 601.2c).

A spell that needs a target must not be offered as castable when the board
has no legal target — it is offered *locked* instead, and casting it is
rejected server-side.
"""

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.effects.core import (
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


def test_protected_creature_is_excluded_from_targets():
    # RULE 702.16b: protection means "can't be the target of spells or
    # abilities from a source of the stated quality" — a red Shock offers no
    # target in a creature that has protection from red.
    eng, p1, p2 = two_player_engine()
    bear = GameObject(
        Card(
            id="Bear",
            name="Bear",
            type_line="Creature — Bear",
            is_creature=True,
            power=2,
            toughness=2,
            oracle_text="Protection from red",
        ),
        owner_id="p2",
        zone=Zone.BATTLEFIELD,
    )
    eng.state.add_to_battlefield(bear)
    red_bolt = give_spell(
        eng, p1, instant("Shock", color_identity={"R"}), [DealDamageEffect(3)]
    )
    opts = targeting.legal_targets(eng.state, p1.id, red_bolt.spell_effects[0].target_spec, source=red_bolt)
    assert "Bear" not in {o.get("name") for o in opts}
    # An off-colour source still sees it.
    blue_bolt = give_spell(
        eng, p1, instant("Unsummon", color_identity={"U"}), [DealDamageEffect(3)]
    )
    opts = targeting.legal_targets(eng.state, p1.id, blue_bolt.spell_effects[0].target_spec, source=blue_bolt)
    assert "Bear" in {o.get("name") for o in opts}


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


# --- PLR-7: a `TargetSpec`'s best-effort good/bad hint ----------------------
#
# `GameEffect.target_polarity()` (game/effects/core.py) feeds `TargetSpec.
# polarity` here, which `requirements_with_targets` then threads onto the
# `cast_spell` action's own requirement dict — the wire contract
# `services/bots.py`'s `GreedyBot` reads to point a removal spell at an
# opponent's permanent and a pump spell at its own.


def test_a_removal_spells_requirement_is_harmful():
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    obj = give_spell(eng, p1, instant("Murder"), [DestroyEffect()])
    action = cast_action_for(eng, p1, obj)
    assert action["targets"][0]["polarity"] == "harmful"


def test_a_pump_spells_requirement_is_beneficial():
    from mtg_analyzer.game.effects.core import PumpEffect

    eng, p1, p2 = two_player_engine()
    obj = give_spell(
        eng, p1, instant("Giant Growth"),
        [PumpEffect(power=3, toughness=3, target_kind="creature")],
    )
    action = cast_action_for(eng, p1, obj)
    assert action["targets"][0]["polarity"] == "beneficial"


def test_a_debuff_pump_spells_requirement_is_harmful():
    from mtg_analyzer.game.effects.core import PumpEffect

    eng, p1, p2 = two_player_engine()
    obj = give_spell(
        eng, p1, instant("Frost Breath"),
        [PumpEffect(power=-2, toughness=-2, target_kind="creature")],
    )
    action = cast_action_for(eng, p1, obj)
    assert action["targets"][0]["polarity"] == "harmful"


def test_an_untargeted_effects_requirement_has_no_polarity_opinion():
    """Not every targeting effect is classified — an unlisted shape stays
    ``None`` rather than guessing (`GameEffect.target_polarity`'s default)."""
    from mtg_analyzer.game.effects.core import RemoveCountersEffect

    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    obj = give_spell(eng, p1, instant("Unbound"), [RemoveCountersEffect(target_kind="permanent")])
    action = cast_action_for(eng, p1, obj)
    assert action["targets"][0]["polarity"] is None


def test_an_aura_with_no_pt_static_has_no_polarity_opinion():
    """A curse Aura's synthesized "enchant" requirement (`targeting.
    _aura_enchant_polarity`) can only read a layer-7 P/T static — a
    keyword-only curse like Pacifism carries none, so this stays ``None``
    (which leaves `GreedyBot`'s "prefer an opponent's permanent" default in
    place — the right call for exactly this shape)."""
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    eng, p1, _ = two_player_engine()
    aura = GameObject(
        Card(
            id="Pacifism", name="Pacifism", type_line="Enchantment — Aura",
            oracle_text="Enchant creature\n~ can't attack or block.",
        ),
        owner_id=p1.id, zone=Zone.HAND,
    )
    bind_from_catalogue(aura)
    specs = targeting.spell_target_specs(aura)
    assert specs and specs[0].polarity is None


def test_an_aura_that_pumps_its_host_is_beneficial():
    """Rancor-shaped: a real layer-7 P/T static on ``attached_permanent``
    is a legible enough signal to flip the default (`targeting.
    _aura_enchant_polarity`)."""
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    eng, p1, _ = two_player_engine()
    aura = GameObject(
        Card(
            id="Rancor", name="Rancor", type_line="Enchantment — Aura",
            oracle_text="Enchant creature\nEnchanted creature gets +2/+0 and has trample.",
        ),
        owner_id=p1.id, zone=Zone.HAND,
    )
    bind_from_catalogue(aura)
    specs = targeting.spell_target_specs(aura)
    assert specs and specs[0].polarity == "beneficial"

"""Tests for ENG-26 — RULE 115/608.2b "target an activated or triggered
ability" (Stifle/Trickbind-shaped).

An ability `StackItem` has no `GameObject` of its own (`.obj` is `None` —
the permanent that has the ability lives on `.source` instead), so nothing
could previously name "an ability on the stack" as a target at all. This
batch adds `StackItem.stack_id` (a stable identity every stack item gets,
spell or ability alike — mirrors `GameObject.instance_id`'s own counter
pattern), `targeting.py`'s ``"ability"``/``"spell_or_ability"`` kinds keyed
by it, `CounterAbilityEffect`/`RulesEngine.counter_ability` (RULE 701.5b),
and extends `ChangeTargetEffect`/`RulesEngine.change_target` to retarget an
ability too (Deflecting Swat's real printed "spell or ability" scope,
previously narrowed to spell-only — see `test_change_target_family.py`).

Reference: mtg_analyzer/game/{effects,targeting}.py,
mtg_analyzer/game/rules/misc_mixin.py, mtg_analyzer/game/ability_catalogue.py,
mtg_analyzer/models/game_state.py (`StackItem.stack_id`).
"""

from mtg_analyzer.game import ability_catalogue, targeting
from mtg_analyzer.game.effects.core import (
    CantBeCounteredEffect,
    CounterAbilityEffect,
    DealDamageEffect,
)
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import StackItem
from mtg_analyzer.models.mana.mana_cost import ManaCost


def instant(name, cost="{0}"):
    return Card(
        id=name, name=name, type_line="Instant", mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost, is_instant=True,
    )


def creature(name="Grizzly Bears", cost="{1}{G}", power=2, toughness=2):
    return Card(
        id=name, name=name, type_line="Creature — Bear", mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_creature=True, power=power, toughness=toughness,
    )


def artifact_source(name="Shock Source", cost="{2}"):
    """A non-creature ability source — so it's never itself a candidate
    "target creature" when a test wants exactly one legal target."""
    return Card(
        id=name, name=name, type_line="Artifact", mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
    )


def two_player_engine():
    filler = instant("Filler")
    eng = GameEngine.new_game(
        [("p1", "Alice", [filler] * 5), ("p2", "Bob", [filler] * 5)],
        starting_hand=0,
    )
    return eng, eng.state.player_by_id("p1"), eng.state.player_by_id("p2")


def battlefield(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(obj)
    return obj


def push_spell(eng, player, card, effects=None, targets=None):
    obj = GameObject(card, owner_id=player.id, zone=Zone.STACK)
    obj.spell_effects = effects or []
    for e in obj.spell_effects:
        e.source = obj
    item = StackItem(
        kind="spell", controller_id=player.id, obj=obj, description=card.name,
        effects=obj.spell_effects, targets=targets or [],
    )
    eng.state.stack.append(item)
    return item


def push_ability(eng, player, source_obj, effects, targets=None, description=None):
    """Put a plain activated/triggered ability directly onto the stack, no
    `.obj` of its own — the shape `StackItem.stack_id` exists for."""
    item = StackItem(
        kind="ability", controller_id=player.id, source=source_obj,
        description=description or f"{source_obj.name}'s ability",
        effects=effects, targets=targets or [],
    )
    eng.state.stack.append(item)
    return item


# ---------------------------------------------------------------------------
# StackItem.stack_id — the identity primitive itself
# ---------------------------------------------------------------------------


def test_every_stack_item_gets_a_unique_stack_id():
    eng, p1, p2 = two_player_engine()
    bear = battlefield(eng, creature(), "p1")
    a = push_spell(eng, p1, instant("Bolt"))
    b = push_ability(eng, p1, bear, [DealDamageEffect(1, target_kind="creature")])
    assert isinstance(a.stack_id, int) and isinstance(b.stack_id, int)
    assert a.stack_id != b.stack_id


# ---------------------------------------------------------------------------
# targeting.py — the "ability" / "spell_or_ability" kinds
# ---------------------------------------------------------------------------


def test_ability_kind_only_offers_ability_items_keyed_by_stack_id():
    eng, p1, p2 = two_player_engine()
    bear = battlefield(eng, creature("Shock Source"), "p2")
    push_spell(eng, p2, instant("Bolt"))
    ability_item = push_ability(eng, p2, bear, [DealDamageEffect(1, target_kind="creature")])
    spec = targeting.TargetSpec(kind="ability")
    opts = targeting.legal_targets(eng.state, "p1", spec)
    assert opts == [{"stack_id": ability_item.stack_id, "name": ability_item.description}]


def test_ability_kind_offers_nothing_when_only_spells_are_on_the_stack():
    eng, p1, p2 = two_player_engine()
    push_spell(eng, p2, instant("Bolt"))
    spec = targeting.TargetSpec(kind="ability")
    assert targeting.legal_targets(eng.state, "p1", spec) == []


def test_spell_or_ability_kind_unions_both():
    eng, p1, p2 = two_player_engine()
    bear = battlefield(eng, creature("Shock Source"), "p2")
    spell_item = push_spell(eng, p2, instant("Bolt"))
    ability_item = push_ability(eng, p2, bear, [DealDamageEffect(1, target_kind="creature")])
    spec = targeting.TargetSpec(kind="spell_or_ability")
    opts = targeting.legal_targets(eng.state, "p1", spec)
    assert {o.get("instance_id") for o in opts if "instance_id" in o} == {spell_item.obj.instance_id}
    assert {o.get("stack_id") for o in opts if "stack_id" in o} == {ability_item.stack_id}


# ---------------------------------------------------------------------------
# RulesEngine.counter_ability (RULE 701.5b) — Stifle/Trickbind's core
# ---------------------------------------------------------------------------


def test_counter_ability_removes_the_ability_from_the_stack():
    eng, p1, p2 = two_player_engine()
    bear = battlefield(eng, creature("Shock Source"), "p2")
    victim = battlefield(eng, creature("Victim", toughness=4), "p2")
    ability_item = push_ability(
        eng, p2, bear, [DealDamageEffect(3, target_kind="creature")], targets=[victim],
    )
    eng.rules.counter_ability(ability_item)
    assert ability_item not in eng.state.stack
    # Countered, never resolved — the target takes no damage.
    assert victim.damage_marked == 0


def test_counter_ability_never_touches_a_spell_item():
    eng, p1, p2 = two_player_engine()
    spell_item = push_spell(eng, p2, instant("Bolt"))
    eng.rules.counter_ability(spell_item)
    assert spell_item in eng.state.stack  # kind != "ability" — refused


def test_counter_ability_refuses_a_cant_be_countered_source():
    eng, p1, p2 = two_player_engine()
    bear = battlefield(eng, creature("Shock Source"), "p2")
    bear.static_effects = [CantBeCounteredEffect()]
    ability_item = push_ability(eng, p2, bear, [DealDamageEffect(1, target_kind="creature")])
    eng.rules.counter_ability(ability_item)
    assert ability_item in eng.state.stack


# ---------------------------------------------------------------------------
# RulesEngine.change_target — now reaching an ability item too (Deflecting
# Swat's real printed "spell or ability" scope)
# ---------------------------------------------------------------------------


def test_change_target_auto_applies_when_the_ability_has_only_one_legal_target():
    # Same "forced, asking would be theatre" idiom as the spell case in
    # `test_change_target_family.py`: with no other creature on the board,
    # the current target is the only legal option — but only a *mandatory*
    # retarget (``optional=False``) skips the choice this way; an optional
    # one still offers "leave it" even with a single alternative (see
    # `test_change_target_family.py`'s own auto-apply test, which is
    # likewise Misdirection-mandatory, not Deflecting-Swat-optional).
    eng, p1, p2 = two_player_engine()
    source_obj = battlefield(eng, artifact_source(), "p2")  # non-creature: never a candidate itself
    victim = battlefield(eng, creature("Victim", toughness=4), "p2")  # the only creature
    ability_item = push_ability(
        eng, p2, source_obj, [DealDamageEffect(3, target_kind="creature")], targets=[victim],
    )
    retargeter = GameObject(instant("Filler"), owner_id="p1", zone=Zone.STACK)
    eng.rules.change_target(ability_item, optional=False, source=retargeter)
    assert eng.state.pending_choice is None
    assert ability_item.targets == [victim]


def test_change_target_ability_opens_a_choice_with_multiple_alternatives():
    eng, p1, p2 = two_player_engine()
    bear = battlefield(eng, creature("Shock Source"), "p2")
    victim = battlefield(eng, creature("Victim", toughness=4), "p2")
    battlefield(eng, creature("Other Victim", toughness=4), "p1")
    ability_item = push_ability(
        eng, p2, bear, [DealDamageEffect(3, target_kind="creature")], targets=[victim],
    )
    swat = GameObject(instant("Deflecting Swat"), owner_id="p1", zone=Zone.STACK)
    eng.rules.change_target(ability_item, optional=True, source=swat)
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "change_target"
    assert choice["stack_id"] == ability_item.stack_id


def test_resolve_change_target_choice_retargets_the_ability():
    eng, p1, p2 = two_player_engine()
    bear = battlefield(eng, creature("Shock Source"), "p2")
    victim = battlefield(eng, creature("Victim", toughness=4), "p2")
    other = battlefield(eng, creature("Other Victim", toughness=4), "p1")
    ability_item = push_ability(
        eng, p2, bear, [DealDamageEffect(3, target_kind="creature")], targets=[victim],
    )
    swat = GameObject(instant("Deflecting Swat"), owner_id="p1", zone=Zone.STACK)
    eng.rules.change_target(ability_item, optional=True, source=swat)
    choice = eng.state.pending_choice
    pick = next(o for o in choice["options"] if o["label"] == "Other Victim")
    eng.rules.resolve_choice(pick["id"])
    assert eng.state.pending_choice is None
    assert ability_item.targets == [other]


# ---------------------------------------------------------------------------
# Hand-authored cards (game/ability_catalogue.py)
# ---------------------------------------------------------------------------


def test_stifle_and_trickbind_are_registered_as_counter_ability():
    for name in ("Stifle", "Trickbind"):
        assert ability_catalogue.is_registered(name)
        specs = ability_catalogue.specs_for(instant(name))
        assert len(specs) == 1
        assert specs[0].effects[0].type == "counter_ability"


def test_stifle_end_to_end_counters_a_real_ability_and_it_never_resolves():
    # Full `GameEngine`-level wiring: a `CounterAbilityEffect` targeting a
    # real ability `StackItem`, resolved through `resolve_until_stable()` —
    # the same shortcut `test_change_target_family.py`'s own end-to-end test
    # uses (build the live effect directly rather than casting from hand).
    eng, p1, p2 = two_player_engine()
    bear = battlefield(eng, creature("Shock Source"), "p2")
    victim = battlefield(eng, creature("Victim", toughness=4), "p2")
    ability_item = push_ability(
        eng, p2, bear, [DealDamageEffect(3, target_kind="creature")], targets=[victim],
    )
    push_spell(
        eng, p1, instant("Stifle"),
        [CounterAbilityEffect(target=ability_item)], targets=[ability_item],
    )
    eng.resolve_until_stable()
    assert ability_item not in eng.state.stack
    assert victim.damage_marked == 0

"""Tests for RULE 115.4/601.2c "change the target" (MEC-12's Misdirection/
Deflecting Swat batch).

Covers the new `ChangeTargetEffect`/`RulesEngine.change_target` primitive: a
genuine retarget of an *existing* stack item, distinct from the already-
shipped "choose new targets for a freshly-made **copy**" (RULE 707.10c).
Single-target-only throughout (no card needs a multi-target retarget yet —
see `ChangeTargetEffect`'s own docstring). The "spell or ability" union
(`spell_or_ability=True`, ENG-26) is covered by
`tests/test_target_ability_family.py` alongside `counter_ability`, both
riding the same `StackItem.stack_id` identity that primitive added.

Reference: mtg_analyzer/game/{effects,targeting}.py,
mtg_analyzer/game/rules/misc_mixin.py, mtg_analyzer/game/ability_catalogue.py.
"""

from mtg_analyzer.game import ability_catalogue, targeting
from mtg_analyzer.game.effects import ChangeTargetEffect, DealDamageEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import StackItem
from mtg_analyzer.models.mana_cost import ManaCost

# ---------------------------------------------------------------------------
# Card factories + fixtures (mirrors tests/test_counter_family.py's style)
# ---------------------------------------------------------------------------


def instant(name, cost="{0}", oracle_text=""):
    return Card(
        id=name,
        name=name,
        type_line="Instant",
        mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_instant=True,
        oracle_text=oracle_text,
    )


def creature(name="Grizzly Bears", cost="{1}{G}", power=2, toughness=2):
    return Card(
        id=name,
        name=name,
        type_line="Creature — Bear",
        mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_creature=True,
        power=power,
        toughness=toughness,
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
    """Put ``card`` directly onto the stack as ``player``'s spell, bypassing
    casting/payment — same helper `test_counter_family.py` uses."""
    obj = GameObject(card, owner_id=player.id, zone=Zone.STACK)
    obj.spell_effects = effects or []
    for e in obj.spell_effects:
        e.source = obj
    item = StackItem(
        kind="spell",
        controller_id=player.id,
        obj=obj,
        description=card.name,
        effects=obj.spell_effects,
        targets=targets or [],
    )
    eng.state.stack.append(item)
    return obj


# ---------------------------------------------------------------------------
# targeting.py: the "spell" kind's `single_target` filter
# ---------------------------------------------------------------------------


def test_single_target_filter_excludes_a_multi_target_spell():
    eng, p1, p2 = two_player_engine()
    bear1 = battlefield(eng, creature("Bear One"), "p2")
    bear2 = battlefield(eng, creature("Bear Two"), "p2")
    push_spell(eng, p2, instant("Single Bolt"), targets=[bear1])
    push_spell(eng, p2, instant("Double Bolt"), targets=[bear1, bear2])
    spec = ChangeTargetEffect(single_target=True).target_spec
    opts = targeting.legal_targets(eng.state, "p1", spec)
    assert {o["name"] for o in opts} == {"Single Bolt"}


def test_no_single_target_filter_offers_every_spell_regardless_of_count():
    eng, p1, p2 = two_player_engine()
    bear1 = battlefield(eng, creature("Bear One"), "p2")
    bear2 = battlefield(eng, creature("Bear Two"), "p2")
    push_spell(eng, p2, instant("Single Bolt"), targets=[bear1])
    push_spell(eng, p2, instant("Double Bolt"), targets=[bear1, bear2])
    spec = ChangeTargetEffect(single_target=False).target_spec
    opts = targeting.legal_targets(eng.state, "p1", spec)
    assert {o["name"] for o in opts} == {"Single Bolt", "Double Bolt"}


# ---------------------------------------------------------------------------
# RulesEngine.change_target — the resolve-time primitive
# ---------------------------------------------------------------------------


def test_change_target_opens_a_choice_with_multiple_alternatives():
    eng, p1, p2 = two_player_engine()
    bear = battlefield(eng, creature("Bear"), "p2")
    battlefield(eng, creature("Other Bear"), "p2")
    battlefield(eng, creature("Third Bear"), "p1")
    victim = push_spell(
        eng, p2, instant("Bolt"), [DealDamageEffect(3, target_kind="creature")], targets=[bear],
    )
    misdirection = GameObject(instant("Misdirection"), owner_id="p1", zone=Zone.STACK)
    eng.rules.change_target(victim, optional=False, source=misdirection)
    choice = eng.state.pending_choice
    assert choice is not None
    assert choice["kind"] == "change_target"
    assert choice["player_id"] == "p1"  # the *changer*, not the victim spell's controller
    assert not any(o["id"] == "decline" for o in choice["options"])  # mandatory


def test_change_target_optional_choice_offers_a_decline():
    eng, p1, p2 = two_player_engine()
    bear = battlefield(eng, creature("Bear"), "p2")
    battlefield(eng, creature("Other Bear"), "p2")
    victim = push_spell(
        eng, p2, instant("Bolt"), [DealDamageEffect(3, target_kind="creature")], targets=[bear],
    )
    swat = GameObject(instant("Deflecting Swat"), owner_id="p1", zone=Zone.STACK)
    eng.rules.change_target(victim, optional=True, source=swat)
    choice = eng.state.pending_choice
    assert choice is not None
    assert any(o["id"] == "decline" for o in choice["options"])


def test_change_target_auto_applies_when_the_current_target_is_the_only_legal_one():
    # RULE 115.4a's "new" target need not differ from the old one — the
    # current target is never excluded from its own legal-targets list.
    # With no other creature on the board, that's the *only* legal option,
    # so there's no real decision to make and no pending_choice opens (same
    # "forced, asking would be theatre" idiom `_choose_objects_choice`
    # uses) — the target is (re-)applied, not left alone by some special
    # case, but the observable result is the same: unchanged.
    eng, p1, p2 = two_player_engine()
    bear = battlefield(eng, creature("Bear"), "p2")  # the only creature at all
    victim = push_spell(
        eng, p2, instant("Bolt"), [DealDamageEffect(3, target_kind="creature")], targets=[bear],
    )
    misdirection = GameObject(instant("Misdirection"), owner_id="p1", zone=Zone.STACK)
    eng.rules.change_target(victim, optional=False, source=misdirection)
    assert eng.state.pending_choice is None
    item = eng.rules._stack_item_for(victim)
    assert item.targets == [bear]


def test_change_target_two_existing_targets_is_left_untouched():
    # This MVP is scoped to a spell with exactly one existing target — see
    # `ChangeTargetEffect`'s own docstring.
    eng, p1, p2 = two_player_engine()
    bear1 = battlefield(eng, creature("Bear One"), "p2")
    bear2 = battlefield(eng, creature("Bear Two"), "p2")
    battlefield(eng, creature("Third Bear"), "p1")
    victim = push_spell(
        eng, p2, instant("Double Bolt"),
        [DealDamageEffect(3, target_kind="creature", count=2)],
        targets=[bear1, bear2],
    )
    misdirection = GameObject(instant("Misdirection"), owner_id="p1", zone=Zone.STACK)
    eng.rules.change_target(victim, optional=False, source=misdirection)
    assert eng.state.pending_choice is None
    item = eng.rules._stack_item_for(victim)
    assert item.targets == [bear1, bear2]


def test_resolve_change_target_choice_retargets_the_spell():
    eng, p1, p2 = two_player_engine()
    bear = battlefield(eng, creature("Bear"), "p2")
    other = battlefield(eng, creature("Other Bear"), "p2")
    third = battlefield(eng, creature("Third Bear"), "p1")
    victim = push_spell(
        eng, p2, instant("Bolt"), [DealDamageEffect(3, target_kind="creature")], targets=[bear],
    )
    misdirection = GameObject(instant("Misdirection"), owner_id="p1", zone=Zone.STACK)
    eng.rules.change_target(victim, optional=False, source=misdirection)
    choice = eng.state.pending_choice
    pick = next(o for o in choice["options"] if o["label"] == "Third Bear")
    assert pick is not None
    eng.rules.resolve_change_target_choice(pick["id"])
    assert eng.state.pending_choice is None
    item = eng.rules._stack_item_for(victim)
    assert item.targets == [third]
    assert item.targets != [bear] and item.targets != [other]


def test_resolve_change_target_choice_decline_leaves_the_target_unchanged():
    eng, p1, p2 = two_player_engine()
    bear = battlefield(eng, creature("Bear"), "p2")
    battlefield(eng, creature("Other Bear"), "p2")
    victim = push_spell(
        eng, p2, instant("Bolt"), [DealDamageEffect(3, target_kind="creature")], targets=[bear],
    )
    swat = GameObject(instant("Deflecting Swat"), owner_id="p1", zone=Zone.STACK)
    eng.rules.change_target(victim, optional=True, source=swat)
    eng.rules.resolve_change_target_choice("decline")
    assert eng.state.pending_choice is None
    item = eng.rules._stack_item_for(victim)
    assert item.targets == [bear]


def test_resolve_pending_choice_dispatches_change_target_and_bolt_resolves_on_the_new_target():
    # Full GameEngine-level wiring: `resolve_pending_choice` → the
    # `change_target` branch → `resolve_until_stable` finishes resolving
    # the retargeted spell against its *new* target.
    eng, p1, p2 = two_player_engine()
    bear = battlefield(eng, creature("Bear", toughness=4), "p2")
    other = battlefield(eng, creature("Other Bear", toughness=4), "p2")
    victim = push_spell(
        eng, p2, instant("Bolt"), [DealDamageEffect(3, target_kind="creature")], targets=[bear],
    )
    misdirection_obj = push_spell(
        eng, p1, instant("Misdirection"),
        [ChangeTargetEffect(target=victim, single_target=True)],
        targets=[victim],
    )
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "change_target"
    pick = next(o for o in choice["options"] if o["label"] == "Other Bear")
    eng.resolve_pending_choice(pick["id"])
    assert eng.state.pending_choice is None
    assert eng.state.stack == []
    assert bear.damage_marked == 0
    assert other.damage_marked == 3


# ---------------------------------------------------------------------------
# Hand-authored cards (game/ability_catalogue.py)
# ---------------------------------------------------------------------------


def test_misdirection_and_deflecting_swat_are_registered():
    assert ability_catalogue.is_registered("Misdirection")
    assert ability_catalogue.is_registered("Deflecting Swat")


def test_misdirection_spec_is_mandatory_single_target_change():
    specs = ability_catalogue.specs_for(instant("Misdirection"))
    assert len(specs) == 1
    effect_spec = specs[0].effects[0]
    assert effect_spec.type == "change_target"
    assert effect_spec.params.get("single_target") is True
    assert not effect_spec.params.get("optional")


def test_deflecting_swat_spec_is_optional_spell_or_ability():
    specs = ability_catalogue.specs_for(instant("Deflecting Swat"))
    assert len(specs) == 1
    effect_spec = specs[0].effects[0]
    assert effect_spec.type == "change_target"
    assert effect_spec.params.get("optional") is True
    assert not effect_spec.params.get("single_target")
    assert effect_spec.params.get("spell_or_ability") is True  # ENG-26

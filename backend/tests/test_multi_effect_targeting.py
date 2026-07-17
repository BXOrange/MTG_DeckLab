"""Tests for `StackItem.target_groups` — 2+ *different* targeting effects on
one spell/ability each resolving against their own target, instead of every
effect on the item reading off the front of one shared ``targets`` list.

Before this, `docs/implementation-state/ToDo_EdgeCases.md` documented this as
a known, deliberately-unfixed boundary (`test_modal_spells.py`'s existing
tests sidestep it by pairing untargeted modes, or the same target twice).
This file exercises the fix directly: `game/rules_engine.py`'s
`resolve_top_of_stack`/`_apply_effects_partitioned` (per-effect group
dispatch), `RulesEngine.cast_spell`/`GameEngine.cast_spell`/`activate_ability`
(``target_groups`` threaded through casting/activation), and the triggered-
ability side — `_trigger_target_specs`/`_continue_trigger_multi_target`/
`resolve_trigger_target_multi_choice` gathering one target per effect,
one choice at a time, mirroring the existing "choose N" iterative pattern.

No real card is known to need this yet (every shipped multi-target/modal
card either has one targeting effect or pairs untargeted modes) — these
tests exercise the mechanism directly via hand-built effects/abilities,
the same style `test_modal_choose_n.py` already uses for its own engine-level
coverage.
"""

import pytest

from mtg_analyzer.game.effects import (
    DealDamageEffect,
    DestroyEffect,
    DrawCardEffect,
    GainLifeEffect,
    TriggeredAbility,
)
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.mana_cost import ManaCost
from mtg_analyzer.services.game_session import GameSession, build_goldfish_engine


def instant(name, cost="{0}"):
    return Card(
        id=name, name=name, type_line="Instant", mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost if cost else 0,
        is_instant=True,
    )


def creature(name="Grizzly Bears", toughness=2):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
                power=2, toughness=toughness)


def artifact(name="Trinket"):
    return Card(id=name, name=name, type_line="Artifact")


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
# Spell casting: `target_groups` partitions targets per effect
# ---------------------------------------------------------------------------


def test_two_different_targeting_effects_each_resolve_against_their_own_group():
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear", toughness=5), owner_id="p2", zone=Zone.BATTLEFIELD)
    trinket = GameObject(artifact(), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    eng.state.add_to_battlefield(trinket)

    obj = give_spell(
        eng, p1, instant("Split Removal"),
        [DealDamageEffect(3, target_kind="creature"), DestroyEffect(target_kind="permanent")],
    )
    eng.cast_spell(p1, obj, target_groups=[[bear], [trinket]])
    item = eng.state.stack[-1]
    assert item.target_groups == [[bear], [trinket]]
    assert item.targets == [bear, trinket]  # flattened union — ward/Aura/display still see both

    eng.rules.resolve_top_of_stack()

    assert bear in eng.state.battlefield  # took 3 damage, survives (5 toughness)
    assert bear.damage_marked == 3
    assert trinket not in eng.state.battlefield  # destroyed by the *other* effect
    assert trinket.zone == Zone.GRAVEYARD


def test_target_groups_via_the_game_session_action_payload():
    # The session/API-level wiring (`_resolve_target_groups`), not just the
    # direct engine call above.
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear", toughness=5), owner_id="p2", zone=Zone.BATTLEFIELD)
    trinket = GameObject(artifact(), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    eng.state.add_to_battlefield(trinket)
    obj = give_spell(
        eng, p1, instant("Split Removal"),
        [DealDamageEffect(3, target_kind="creature"), DestroyEffect(target_kind="permanent")],
    )
    session = GameSession(eng)

    session.apply_action({
        "type": "cast_spell",
        "instance_id": obj.instance_id,
        "target_groups": [
            [{"instance_id": bear.instance_id}],
            [{"instance_id": trinket.instance_id}],
        ],
    })
    session.apply_action({"type": "pass_priority"})

    assert bear in eng.state.battlefield and bear.damage_marked == 3
    assert trinket not in eng.state.battlefield


def test_without_target_groups_a_single_targeting_effect_is_unaffected():
    # Backward compatibility: omitting `target_groups` (the overwhelming
    # common case — at most one targeting effect) behaves exactly as before.
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    obj = give_spell(eng, p1, instant("Shock"), [DealDamageEffect(3, target_kind="creature")])
    eng.cast_spell(p1, obj, targets=[bear])
    item = eng.state.stack[-1]
    assert item.target_groups is None

    eng.rules.resolve_top_of_stack()
    assert bear not in eng.state.battlefield


# ---------------------------------------------------------------------------
# Triggered abilities: one target gathered per effect, one choice at a time
# ---------------------------------------------------------------------------


def _put(eng, card, controller="p2"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    return obj


def _two_effect_trigger(source, optional=False):
    return TriggeredAbility(
        trigger_event="ENTERS_BATTLEFIELD",
        effects=[DealDamageEffect(3, target_kind="creature"), DestroyEffect(target_kind="permanent")],
        optional=optional,
        controller_id="p1",
        source=source,
        description="deal 3 damage to target creature and destroy target artifact",
    )


def test_trigger_with_two_different_effects_offers_one_choice_per_effect():
    eng, p1, p2 = two_player_engine()
    source = _put(eng, creature("Source"), controller="p1")
    bear = _put(eng, creature("Bear", toughness=5))
    trinket = _put(eng, artifact())

    eng.rules.pending_triggers = [(_two_effect_trigger(source), None)]
    eng.rules.put_triggers_on_stack()

    choice = eng.state.pending_choice
    assert choice["kind"] == "trigger_target_multi"
    # First spec is "creature" — only Bear is offered, not the artifact.
    assert {o["label"] for o in choice["options"]} == {"Bear"}

    eng.rules.resolve_trigger_target_multi_choice(str(bear.instance_id))
    choice = eng.state.pending_choice
    assert choice["kind"] == "trigger_target_multi"
    # Second spec is "permanent" — both remaining objects are legal.
    assert {o["label"] for o in choice["options"]} == {"Bear", "Trinket"}

    eng.rules.resolve_trigger_target_multi_choice(str(trinket.instance_id))
    assert eng.state.pending_choice is None
    assert len(eng.state.stack) == 1

    eng.resolve_until_stable()
    assert bear in eng.state.battlefield and bear.damage_marked == 3
    assert trinket not in eng.state.battlefield


def test_trigger_target_multi_decline_on_first_pick_abandons_whole_ability():
    eng, p1, p2 = two_player_engine()
    source = _put(eng, creature("Source"), controller="p1")
    bear = _put(eng, creature("Bear"))
    trinket = _put(eng, artifact())

    eng.rules.pending_triggers = [(_two_effect_trigger(source, optional=True), None)]
    eng.rules.put_triggers_on_stack()
    choice = eng.state.pending_choice
    assert any(o["id"] == "decline" for o in choice["options"])  # RULE 603.5, first pick only

    eng.rules.resolve_trigger_target_multi_choice("decline")
    assert eng.state.pending_choice is None
    assert not eng.state.stack  # nothing placed at all
    assert bear in eng.state.battlefield
    assert trinket in eng.state.battlefield


def test_trigger_target_multi_second_spec_offers_no_decline():
    eng, p1, p2 = two_player_engine()
    source = _put(eng, creature("Source"), controller="p1")
    bear = _put(eng, creature("Bear"))
    trinket = _put(eng, artifact())

    eng.rules.pending_triggers = [(_two_effect_trigger(source, optional=True), None)]
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_trigger_target_multi_choice(str(bear.instance_id))

    choice = eng.state.pending_choice
    assert not any(o["id"] == "decline" for o in choice["options"])


def test_trigger_required_spec_with_no_legal_target_drops_the_whole_ability():
    # RULE 603.3c: the first (mandatory, "creature") spec has nothing legal
    # to target — the ability never goes on the stack, even though the
    # second spec ("permanent") would have had a legal option.
    eng, p1, p2 = two_player_engine()
    source = _put(eng, creature("Source"), controller="p1")
    trinket = _put(eng, artifact())

    eng.rules.pending_triggers = [(_two_effect_trigger(source), None)]
    eng.rules.put_triggers_on_stack()

    assert eng.state.pending_choice is None
    assert not eng.state.stack
    assert trinket in eng.state.battlefield


def test_trigger_optional_second_spec_with_no_legal_target_is_skipped():
    from mtg_analyzer.game.effects import DestroyEffect as _DestroyEffect

    eng, p1, p2 = two_player_engine()
    source = _put(eng, creature("Source"), controller="p1")
    # The second spec targets "land you control" — no lands exist anywhere
    # on this hand-built board, so it's guaranteed zero legal options
    # (unlike "permanent", which the first spec's own creature target would
    # also satisfy).
    ability = TriggeredAbility(
        trigger_event="ENTERS_BATTLEFIELD",
        effects=[
            DealDamageEffect(3, target_kind="creature"),
            _DestroyEffect(target_kind="land_you_control", optional=True),
        ],
        controller_id="p1",
        source=source,
    )
    bear = _put(eng, creature("Bear", toughness=5))
    # No lands on the board at all — the "up to one" second spec has
    # nothing to offer and is silently skipped (empty group), rather than
    # dropping the whole ability.

    eng.rules.pending_triggers = [(ability, None)]
    eng.rules.put_triggers_on_stack()
    choice = eng.state.pending_choice
    assert choice["kind"] == "trigger_target_multi"
    assert {o["label"] for o in choice["options"]} == {"Bear"}

    eng.rules.resolve_trigger_target_multi_choice(str(bear.instance_id))
    assert eng.state.pending_choice is None
    assert len(eng.state.stack) == 1

    eng.resolve_until_stable()
    assert bear in eng.state.battlefield and bear.damage_marked == 3


# ---------------------------------------------------------------------------
# Modal spell: 2 chosen modes with *different* targets combine correctly
# ---------------------------------------------------------------------------


def test_modal_two_modes_with_different_targets_combine_via_target_groups():
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear", toughness=5), owner_id="p2", zone=Zone.BATTLEFIELD)
    trinket = GameObject(artifact(), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    eng.state.add_to_battlefield(trinket)

    obj = GameObject(instant("Test Command"), owner_id="p1", zone=Zone.HAND)
    obj.spell_modes = [
        {"effects": [DestroyEffect(target_kind="permanent")], "description": "destroy target artifact"},
        {"effects": [DealDamageEffect(3, target_kind="creature")], "description": "deal 3 damage to target creature"},
        {"effects": [GainLifeEffect(amount=3)], "description": "gain 3 life"},
        {"effects": [DrawCardEffect(count=1)], "description": "draw a card"},
    ]
    obj.spell_modes_choose = 2
    p1.hand.append(obj)

    # Modes 0 and 1 combine in printed order, so target_groups follows the
    # same order: mode 0's target (the artifact) first, mode 1's (the bear)
    # second.
    eng.cast_spell(p1, obj, mode=[1, 0], target_groups=[[trinket], [bear]])
    eng.rules.resolve_top_of_stack()

    assert trinket not in eng.state.battlefield
    assert bear in eng.state.battlefield and bear.damage_marked == 3

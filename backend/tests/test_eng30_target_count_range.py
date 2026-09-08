"""Tests for ENG-30: RULE 601.2c's third target-count shape — a genuine
*range* ("one or two target creatures": at least one, at most two), as
opposed to `test_multi_target.py`'s exact/optional N and
`test_optional_targets.py`'s "up to one".

`TargetSpec.count_max` is the new field (`game/targeting.py`); ``count``
stays the RULE 601.2c *minimum* everywhere it already meant "the" count —
offer-time locking (`all_requirements_satisfiable`) and trigger-target
gathering (`expand_counts`) both read it unchanged. ``count_max`` only
changes two things: `TargetSpec.effective_count` (the real slicing cap
`game/effects/core.py` uses instead of ``count`` — a range spec's ``count`` is
too small a cap and would silently drop a legally-chosen second target) and
how many rounds get offered (client-side `expandMultiTargetRequirements` for
a spell/ability cast, `expand_counts` for a trigger's own target gathering).

Mirrors `test_multi_target.py`'s fixture pattern and parser-recognition-
then-engine-drive split; the trigger-target gathering path (a 2-round
`pending_choice`, first mandatory then declinable) is covered end-to-end by
`test_mec28_intervening_if_residual.py`'s Raph & Leo, Sibling Rivals tests
instead of duplicated here.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.effects.core import AddCountersEffect, DealDamageEffect, PumpEffect, TapEffect
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import TargetSpec, all_requirements_satisfiable, requirements_with_targets
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.mana_cost import ManaCost
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def instant(name, cost="{0}", oracle_text=""):
    return Card(
        id=name, name=name, type_line="Instant", mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost if cost else 0,
        is_instant=True, oracle_text=oracle_text,
    )


def creature(name="Grizzly Bears", power=2, toughness=2):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
                power=power, toughness=toughness)


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


def _card(name: str):
    if not DEFAULT_DB_PATH.exists():
        pytest.skip("card cache not present in this environment")
    db = CardDatabase(DEFAULT_DB_PATH)
    card = db.get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not present in the local card cache")
    return card


# ---------------------------------------------------------------------------
# PARSER RECOGNITION
# ---------------------------------------------------------------------------


def test_divided_damage_range_recognized():
    # Electrolyze/Forked Bolt-shaped: "~ deals 2 damage divided as you
    # choose among 1 or 2 targets."
    (spec,) = parse_effect_body("~ deals 2 damage divided as you choose among 1 or 2 targets")
    assert spec.type == "damage"
    assert spec.params == {
        "amount": 2, "target_kind": "any", "count": 1, "count_max": 2, "divided": True,
    }
    assert "optional" not in spec.params  # a range is never "up to" — the floor is 1, not 0


def test_damage_each_range_recognized():
    # Storm of Steel-shaped: "~ deals 2 damage to each of 1 or 2 targets."
    (spec,) = parse_effect_body("~ deals 2 damage to each of 1 or 2 targets")
    assert spec.type == "damage"
    assert spec.params == {"amount": 2, "target_kind": "any", "count": 1, "count_max": 2}


def test_distribute_counters_range_recognized():
    # Armament Corps-shaped: "distribute 2 +1/+1 counters among 1 or 2
    # target creatures you control."
    (spec,) = parse_effect_body(
        "distribute 2 +1/+1 counters among 1 or 2 target creatures you control"
    )
    assert spec.type == "add_counters"
    assert spec.params == {
        "count": 2, "kind": "+1/+1", "target_kind": "creature_you_control",
        "target_count": 1, "target_count_max": 2, "divided": True,
    }


def test_pump_range_recognized():
    # Opera Love Song-shaped: "1 or 2 target creatures each get +2/+0 until
    # end of turn."
    (spec,) = parse_effect_body("1 or 2 target creatures each get +2/+0 until end of turn")
    assert spec.type == "pump"
    assert spec.params == {
        "power": 2, "toughness": 0, "target_kind": "creature",
        "target_count": 1, "target_count_max": 2,
    }


def test_pump_range_keyword_only_recognized():
    # Wind Sail-shaped: "1 or 2 target creatures gain flying until end of turn."
    (spec,) = parse_effect_body("1 or 2 target creatures gain flying until end of turn")
    assert spec.type == "pump"
    assert spec.params == {
        "target_kind": "creature", "target_count": 1, "target_count_max": 2,
        "keywords": ["flying"],
    }


def test_tap_multi_target_range_recognized():
    # Broken Dam-shaped grammar (the range half only — the "without
    # horsemanship" filter tail is a separate, still-open gap).
    (spec,) = parse_effect_body("tap 1 or 2 target creatures")
    assert spec.type == "tap"
    assert spec.params == {"target_kind": "creature", "count": 1, "count_max": 2, "untap": False}


def test_return_to_hand_range_recognized():
    # Counterintelligence-shaped: "return 1 or 2 target creatures to their
    # owners' hands."
    (spec,) = parse_effect_body("return 1 or 2 target creatures to their owners' hands")
    assert spec.type == "return_to_hand"
    assert spec.params == {"target_kind": "creature", "count": 1, "count_max": 2}


def test_return_to_hand_nonland_permanent_range_recognized():
    # Wanderwine Farewell's own first clause (its second clause, a
    # count-selector token creation, is a separate open gap).
    (spec,) = parse_effect_body("return 1 or 2 target nonland permanents to their owners' hands")
    assert spec.type == "return_to_hand"
    assert spec.params == {"target_kind": "nonland_permanent", "count": 1, "count_max": 2}


def test_return_from_graveyard_range_recognized():
    # Infernal Rebirth-shaped: "return 1 or 2 target creature cards from
    # your graveyard to your hand."
    (spec,) = parse_effect_body(
        "return 1 or 2 target creature cards from your graveyard to your hand"
    )
    assert spec.type == "return_from_graveyard"
    assert spec.params == {
        "target_kind": "graveyard_creature", "destination": "hand", "count": 1, "count_max": 2,
    }


def test_degenerate_range_stays_unclaimed():
    # A range whose max isn't strictly above its min ("1 or 1"/"2 or 1")
    # never appears on a real card — fail closed rather than silently
    # treating it as an ordinary fixed count.
    assert parse_effect_body("tap 1 or 1 target creatures") is None
    assert parse_effect_body("tap 2 or 1 target creatures") is None


def test_up_to_two_pump_bug_fix_reaches_target_spec():
    # ENG-30 found and fixed a dormant bug alongside the range work: "up to
    # two target creatures…" (Dauntless Onslaught-shaped, unrelated to the
    # range shape) was silently only ever offering *one* target, since the
    # handler set a "count" key the "pump" EffectRegistry factory never
    # read (it reads "target_count"). Confirmed fixed here since it's the
    # same neighboring handler this ticket touched.
    (spec,) = parse_effect_body(
        "up to 2 target creatures each get +1/+1 until end of turn"
    )
    assert spec.params.get("target_count") == 2
    assert spec.params.get("optional") is True


# ---------------------------------------------------------------------------
# TARGETSPEC / EFFECT CLASSES: count_max propagates, effective_count is the
# real slicing cap
# ---------------------------------------------------------------------------


def test_effective_count_falls_back_to_count_when_no_range():
    assert TargetSpec(count=1).effective_count == 1
    assert TargetSpec(count=2).effective_count == 2


def test_effective_count_is_count_max_for_a_range():
    assert TargetSpec(count=1, count_max=2).effective_count == 2


def test_count_max_reaches_target_spec_across_effect_classes():
    assert DealDamageEffect(2, count=1, count_max=2, divided=True).target_spec.count_max == 2
    assert TapEffect(count=1, count_max=2).target_spec.count_max == 2
    assert AddCountersEffect(target_kind="creature", count=1, count_max=2).target_spec.count_max == 2
    assert PumpEffect(target_kind="creature", count=1, count_max=2).target_spec.count_max == 2
    # Default stays None (ordinary fixed/"up to N" specs are unaffected).
    assert DealDamageEffect(2).target_spec.count_max is None


# ---------------------------------------------------------------------------
# ENGINE: RULE 601.2c castability — a range needs >= the *minimum* legal
# targets to be castable at all, never the maximum
# ---------------------------------------------------------------------------


def test_range_locks_with_zero_legal_targets():
    eng, p1, p2 = two_player_engine()
    obj = give_spell(
        eng, p1, instant("Split Bolt"),
        [DealDamageEffect(2, target_kind="creature", count=1, count_max=2, divided=True)],
    )
    action = cast_action_for(eng, p1, obj)
    assert action.get("locked") is True


def test_range_castable_with_only_the_minimum_legal_target():
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    obj = give_spell(
        eng, p1, instant("Split Bolt"),
        [DealDamageEffect(2, target_kind="creature", count=1, count_max=2, divided=True)],
    )
    action = cast_action_for(eng, p1, obj)
    assert action.get("locked") is None
    assert action["targets"][0]["count"] == 1
    assert action["targets"][0]["count_max"] == 2


# ---------------------------------------------------------------------------
# ENGINE: resolution honours whichever count (1 or 2) was actually chosen
# ---------------------------------------------------------------------------


def test_choosing_one_target_in_a_range_resolves_against_just_that_one():
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    wolf = GameObject(creature("Wolf"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    eng.state.add_to_battlefield(wolf)
    obj = give_spell(
        eng, p1, instant("Split Bolt"),
        [DealDamageEffect(4, target_kind="creature", count=1, count_max=2, divided=True)],
    )
    eng.cast_spell(p1, obj, targets=[bear])
    eng.rules.resolve_top_of_stack()
    eng.rules.check_state_based_actions()
    assert bear not in eng.state.battlefield  # took all 4
    assert wolf in eng.state.battlefield  # untouched


def test_choosing_both_targets_in_a_range_is_not_truncated_to_the_minimum():
    # The bug `effective_count` exists to prevent: if resolution sliced by
    # `count` (the minimum, 1) instead of `count_max`, a legally-chosen
    # second target would be silently dropped.
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    wolf = GameObject(creature("Wolf"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    eng.state.add_to_battlefield(wolf)
    obj = give_spell(
        eng, p1, instant("Split Bolt"),
        [DealDamageEffect(4, target_kind="creature", count=1, count_max=2, divided=True)],
    )
    eng.cast_spell(p1, obj, targets=[bear, wolf])
    eng.rules.resolve_top_of_stack()
    eng.rules.check_state_based_actions()
    assert bear not in eng.state.battlefield  # 2 damage each (divided)
    assert wolf not in eng.state.battlefield


def test_tap_range_effective_count_caps_at_the_max_not_the_min():
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    bear.tapped = True
    wolf = GameObject(creature("Wolf"), owner_id="p2", zone=Zone.BATTLEFIELD)
    wolf.tapped = True
    eng.state.add_to_battlefield(bear)
    eng.state.add_to_battlefield(wolf)
    obj = give_spell(
        eng, p1, instant("Double Untap"),
        [TapEffect(target_kind="creature", untap=True, count=1, count_max=2)],
    )
    eng.cast_spell(p1, obj, targets=[bear, wolf])
    eng.rules.resolve_top_of_stack()
    assert bear.tapped is False
    assert wolf.tapped is False


# ---------------------------------------------------------------------------
# END-TO-END: real card oracle text -> parse -> bind -> cast -> resolve
# ---------------------------------------------------------------------------


def test_electrolyze_end_to_end():
    card = _card("Electrolyze")
    result = parse_oracle(card)
    assert result.coverage == MODELED

    eng, p1, p2 = two_player_engine()
    # 1-toughness creatures: Electrolyze splits 2 damage evenly across 1 or
    # 2 chosen targets, so 2 targets means 1 damage each — enough to kill
    # these, unambiguously proving the split reached *both*.
    bear = GameObject(creature("Bear", power=1, toughness=1), owner_id="p2", zone=Zone.BATTLEFIELD)
    wolf = GameObject(creature("Wolf", power=1, toughness=1), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    eng.state.add_to_battlefield(wolf)

    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)

    requirements = requirements_with_targets(eng.state, "p1", obj)
    damage_req = next(r for r in requirements if r["kind"] == "any")
    assert damage_req["count"] == 1
    assert damage_req["count_max"] == 2
    assert all_requirements_satisfiable(requirements)  # 1 legal target is enough

    p1.mana_pool.add_many({"U": 1, "R": 1, "C": 1})
    eng.cast_spell(p1, obj, targets=[bear, wolf])
    eng.rules.resolve_top_of_stack()
    eng.rules.check_state_based_actions()
    assert bear not in eng.state.battlefield  # 1 damage each, split from 2
    assert wolf not in eng.state.battlefield


def test_armament_corps_end_to_end():
    card = _card("Armament Corps")
    result = parse_oracle(card)
    assert result.coverage == MODELED

    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)

    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)

    from mtg_analyzer.models.events import EventType, GameEvent

    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id="p1", instance_id=obj.instance_id,
        object=obj.name, object_types=sorted(obj.type_words),
    ))
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1

    choice = eng.state.pending_choice
    # The range expands to 2 rounds (RULE 601.2c's ceiling) even with only
    # two legal creatures you control (Armament Corps itself is a legal
    # target of its own trigger — RULE 115 doesn't exclude the source
    # unless the effect says "another") — this first round is mandatory:
    # no decline/"stop" option yet.
    assert choice is not None and choice["kind"] == "trigger_target_multi"
    assert {opt["instance_id"] for opt in choice["options"]} == {bear.instance_id, obj.instance_id}
    assert not any(opt.get("id") in ("decline", "stop") for opt in choice["options"])
    eng.resolve_pending_choice(str(bear.instance_id))
    eng.resolve_until_stable()
    # Round 2: the one remaining legal creature (Armament Corps itself) plus
    # the "stop early" option, since the printed maximum is two but the
    # minimum is already satisfied.
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target_multi"
    assert {opt["instance_id"] for opt in choice["options"] if "instance_id" in opt} == {obj.instance_id}
    assert any(opt.get("id") == "stop" for opt in choice["options"])
    eng.resolve_pending_choice("stop")
    eng.resolve_until_stable()
    assert bear.counters.get("+1/+1", 0) == 2  # sole chosen target gets the whole pool


def test_dauntless_onslaught_offers_up_to_two_after_the_bug_fix():
    # Real-card confirmation of the dormant "up to two" bug fixed alongside
    # this ticket's own neighboring handler (see `test_up_to_two_pump_bug_
    # fix_reaches_target_spec` for the parser-level assertion).
    card = _card("Dauntless Onslaught")
    result = parse_oracle(card)
    assert result.coverage == MODELED

    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p1", zone=Zone.BATTLEFIELD)
    wolf = GameObject(creature("Wolf"), owner_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    eng.state.add_to_battlefield(wolf)

    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)

    requirements = requirements_with_targets(eng.state, "p1", obj)
    assert requirements[0]["count"] == 2
    assert requirements[0]["optional"] is True

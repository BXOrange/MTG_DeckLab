"""Tests for a conditional Flash/instant-speed-activation permission (RULE
702.8b/606.3, The Wandering Emperor-shaped): "you may cast this spell as
though it had flash if <condition>" / "you may activate this permanent's
loyalty abilities any time you could cast an instant if <condition>".

Distinct from `EffectSpec.condition` (gates whether a *resolving effect*
applies) — this gates *cast/activation legality* instead
(`game/condition_query.py`, `parser/oracle/spec.py`'s
``ALLOWED_CAST_CONDITION_KEYS``).
"""

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.effects.core import DealDamageEffect, TriggeredAbility
from mtg_analyzer.models.game.game_state import StackItem
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.game import condition_query
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec, SpecValidationError


def make_engine(hand=0):
    cards = [Card(id=f"Bear{i}", name=f"Bear{i}", type_line="Creature", is_creature=True)
             for i in range(6)]
    return GameEngine.new_game([("p1", "Alice", cards)], starting_life=20, starting_hand=hand)


# ---------------------------------------------------------------------------
# Spec validation (parser/oracle/spec.py)
# ---------------------------------------------------------------------------


def test_conditional_flash_accepts_the_whitelisted_key():
    spec = AbilitySpec(
        "spell_effect", [EffectSpec("damage", {"amount": 1, "target_kind": "any"})],
        conditional_flash={"entered_this_turn": True},
    )
    spec.validate()  # does not raise


def test_conditional_flash_rejects_an_unknown_key():
    spec = AbilitySpec(
        "spell_effect", [EffectSpec("damage", {"amount": 1, "target_kind": "any"})],
        conditional_flash={"controls_type": "Wizard"},
    )
    with pytest.raises(SpecValidationError):
        spec.validate()


def test_conditional_flash_rejects_a_multi_key_dict():
    spec = AbilitySpec(
        "spell_effect", [EffectSpec("damage", {"amount": 1, "target_kind": "any"})],
        conditional_flash={"entered_this_turn": True, "extra": 1},
    )
    with pytest.raises(SpecValidationError):
        spec.validate()


# ---------------------------------------------------------------------------
# condition_query.conditional_flash_holds
# ---------------------------------------------------------------------------


def test_entered_this_turn_holds_only_on_the_entry_turn():
    eng = make_engine()
    eng.begin_turn()
    obj = GameObject(Card(id="PW", name="PW", type_line="Planeswalker"), owner_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(obj)
    assert condition_query.conditional_flash_holds({"entered_this_turn": True}, obj, eng.state) is True

    eng.begin_turn()  # advance to the next turn
    assert condition_query.conditional_flash_holds({"entered_this_turn": True}, obj, eng.state) is False


# ---------------------------------------------------------------------------
# can_cast: a conditional-Flash spell (synthetic — validates the generic
# wiring; "entered_this_turn" is normally only meaningful for a permanent
# already on the battlefield, but `can_cast` doesn't care what the
# condition key means, only whether `conditional_flash_holds` says yes)
# ---------------------------------------------------------------------------


def test_can_cast_a_conditional_flash_sorcery_outside_the_main_phase():
    eng = make_engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "combat_damage"  # not a main phase
    p1 = eng.state.active_player
    card = Card(id="Cond", name="Cond", type_line="Sorcery",
                mana_cost_string="{R}", converted_mana_cost=1, is_sorcery=True)
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(obj, Zone.HAND)
    p1.mana_pool.add("R", 1)

    assert eng.can_cast(p1, obj) is False  # ordinarily sorcery-speed only

    obj.conditional_flash = {"entered_this_turn": True}
    obj.turn_entered = eng.state.internal_turn.number  # synthetic: pretend the condition holds
    assert eng.can_cast(p1, obj) is True

    obj.turn_entered = eng.state.internal_turn.number - 1  # condition no longer holds
    assert eng.can_cast(p1, obj) is False


# ---------------------------------------------------------------------------
# The Wandering Emperor: conditional instant-speed loyalty activation
# ---------------------------------------------------------------------------


def _wandering_emperor(eng, p1):
    card = Card(id="The Wandering Emperor", name="The Wandering Emperor",
                type_line="Legendary Planeswalker — Emperor", loyalty=3)
    obj = GameObject(card, owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    obj.summoning_sick = False
    return obj


def test_wandering_emperor_can_activate_loyalty_with_a_full_stack_the_turn_it_enters():
    eng = make_engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    pw = _wandering_emperor(eng, p1)
    ability = pw.activated_abilities[0]  # +1
    assert ability.cost.loyalty == 1

    # Stack non-empty — ordinarily illegal at sorcery speed.
    eng.state.stack.append(StackItem(kind="ability", controller_id="p1", effects=[
        TriggeredAbility(trigger_event=EventType.DAMAGE, effects=[])
    ]))
    assert eng.can_activate(p1, pw, ability) is True


def test_wandering_emperor_loses_instant_speed_after_the_turn_it_entered():
    eng = make_engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    pw = _wandering_emperor(eng, p1)
    ability = pw.activated_abilities[0]

    eng.begin_turn()  # advance — no longer "entered this turn"
    eng.state.current_step = "main1"
    eng.state.stack.append(StackItem(kind="ability", controller_id="p1", effects=[
        TriggeredAbility(trigger_event=EventType.DAMAGE, effects=[])
    ]))
    assert eng.can_activate(p1, pw, ability) is False
    eng.state.stack.clear()
    assert eng.can_activate(p1, pw, ability) is True  # still fine at ordinary sorcery speed


def test_wandering_emperor_specs_carry_the_conditional_flash():
    card = Card(id="The Wandering Emperor", name="The Wandering Emperor", type_line="Planeswalker")
    specs = specs_for(card)
    assert any(spec.conditional_flash == {"entered_this_turn": True} for spec in specs)

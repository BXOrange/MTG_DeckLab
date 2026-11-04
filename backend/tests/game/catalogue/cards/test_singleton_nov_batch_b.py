"""Singleton gameplay regressions with inline Oracle fixtures (no card cache)."""
from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.continuous import granted_help_pay_keyword
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import StackItem


def engine():
    return GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)


def obj(eng, name, kind="Creature", zone=Zone.BATTLEFIELD, player="p1", **kwargs):
    card = Card(id=name, name=name, type_line=kind,
                is_creature="Creature" in kind, is_instant="Instant" in kind,
                **kwargs)
    result = GameObject(card, owner_id=player, zone=zone)
    result.controller_id = player
    result.summoning_sick = False
    bind_from_catalogue(result)
    if zone == Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(result)
    else:
        eng.state.player_by_id(player).add_to_zone(result, zone)
    return result


@pytest.mark.parametrize("wizard", [True, False])
@pytest.mark.parametrize("uncounterable", [True, False])
def test_mana_sculpt_uses_paid_mana_and_resolution_wizard(wizard, uncounterable):
    eng = engine()
    if wizard:
        obj(eng, "Wizard", "Creature — Wizard", power=1, toughness=1)
    target = obj(eng, "Large Spell", "Instant", zone=Zone.HAND,
                 player="p2", converted_mana_cost=9)
    eng.state.player_by_id("p2").hand.remove(target)
    target.zone = Zone.STACK
    target.mana_spent_to_cast = 3
    if uncounterable:
        from mtg_analyzer.game.effects.stack import CantBeCounteredEffect
        target.spell_effects = [CantBeCounteredEffect()]
    eng.state.stack.append(StackItem(kind="spell", controller_id="p2", obj=target, effects=[]))
    source = obj(eng, "Mana Sculpt", "Instant", zone=Zone.HAND)
    eng.state.stack.append(StackItem(kind="ability", controller_id="p1", source=source,
                                     effects=source.spell_effects, targets=[target]))
    eng.rules.resolve_top_of_stack()
    delayed = eng.state.delayed_triggers
    assert len(delayed) == int(wizard)
    if wizard:
        assert delayed[0].effects[0].amount == 3
    assert (target.zone == Zone.STACK) == uncounterable
    if wizard:
        # Opponent's main phase cannot spend the delayed trigger.
        eng.state.active_player_index = 1
        eng._fire_delayed_triggers("main1")
        assert len(eng.state.delayed_triggers) == 1
        eng.state.active_player_index = 0
        eng._fire_delayed_triggers("main2")
        eng.resolve_until_stable()
        assert eng.state.player_by_id("p1").mana_pool.total() == 3
        eng._fire_delayed_triggers("main1")
        eng.resolve_until_stable()
        assert eng.state.player_by_id("p1").mana_pool.total() == 3


@pytest.mark.parametrize("zone,kind,player,expected", [
    (Zone.EXILE, "Instant", "p1", "convoke"),
    (Zone.HAND, "Instant", "p1", None),
    (Zone.EXILE, "Creature", "p1", None),
    (Zone.EXILE, "Instant", "p2", None),
])
def test_party_thrasher_only_own_exiled_noncreatures(zone, kind, player, expected):
    eng = engine()
    obj(eng, "Party Thrasher", power=1, toughness=4)
    spell = obj(eng, "Spell", kind, zone, player)
    assert granted_help_pay_keyword(eng.state, spell) == expected


def test_moonveil_can_discard_empty_hand_and_uses_cast_color_snapshot():
    eng = engine()
    regent = obj(eng, "Moonveil Regent", power=4, toughness=4)
    p1 = eng.state.player_by_id("p1")
    for index in range(5):
        obj(eng, f"Draw {index}", "Instant", Zone.LIBRARY)
    # The spell has already left the stack. Its casting-event snapshot survives.
    eng.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p1", instance_id=-1,
                                   colors=["U", "R"]))
    eng.resolve_until_stable()
    assert eng.state.pending_choice
    options = eng.state.pending_choice["options"]
    accept = next(option["id"] for option in options if str(option["id"]) in ("yes", "accept", "do"))
    eng.resolve_pending_choice(str(accept))
    eng.resolve_until_stable()
    assert len(p1.hand) == 2
    assert "flying" in regent.intrinsic_keywords


def test_factories_return_fresh_specs():
    for name in ("Mana Sculpt", "Moonveil Regent", "Party Thrasher"):
        card = Card(id=name, name=name, type_line="Creature")
        first, second = specs_for(card), specs_for(card)
        assert first and first is not second and first[0] is not second[0]


def test_party_thrasher_pays_actual_exile_spell_with_convoke():
    eng = engine()
    eng.state.current_step = "main1"
    helper = obj(eng, "Party Thrasher", power=1, toughness=4)
    player = eng.state.player_by_id("p1")
    spell = obj(eng, "Convoke spell", "Instant", Zone.EXILE, mana_cost_string="{1}",
                oracle_text="You gain 3 life.")
    eng.state.temp_play_permissions[spell.instance_id] = eng.state.internal_turn.number
    assert eng.can_cast(player, spell, help_pay=True)
    eng.cast_spell(player, spell, help_pay=True)
    eng.resolve_until_stable()
    assert helper.tapped and spell.zone == Zone.GRAVEYARD
    assert player.life == 43
    assert spell.mana_spent_to_cast == 0


def test_osgir_chooses_matching_cost_card_and_snapshot_survives_move():
    eng = engine()
    eng.state.current_step = "main1"
    player = eng.state.player_by_id("p1")
    source = obj(eng, "Osgir, the Reconstructor", power=4, toughness=4)
    wrong = obj(eng, "Wrong artifact", "Artifact", Zone.GRAVEYARD, converted_mana_cost=1)
    first = obj(eng, "First artifact", "Artifact", Zone.GRAVEYARD, converted_mana_cost=2)
    selected = obj(eng, "Selected artifact", "Artifact", Zone.GRAVEYARD, converted_mana_cost=2)
    player.mana_pool.add("C", 2)
    with pytest.raises(ValueError):
        eng.activate_ability(player, source, 1, x=2, hand_card_choices=[wrong.instance_id])
    assert not source.tapped and player.mana_pool.total() == 2
    assert any(action["type"] == "activate_ability" and action.get("ability_index") == 1
               for action in eng.legal_actions(player))
    eng.activate_ability(player, source, 1, x=2, hand_card_choices=[selected.instance_id])
    assert selected.zone == Zone.EXILE and first.zone == Zone.GRAVEYARD
    assert eng.state.stack[-1].trigger_event.get("cost_exiled_ids") == [selected.instance_id]
    eng.rules.return_to_hand(selected)
    eng.resolve_until_stable()
    tokens = [o for o in eng.state.battlefield if o.is_token and o.name == "Selected artifact"]
    assert len(tokens) == 2, [(o.name, o.is_token) for o in eng.state.battlefield]
    assert source.tapped and player.mana_pool.total() == 0


def test_ravenous_announces_division_freezes_power_and_retaliates_before_death():
    eng = engine()
    source = obj(eng, "Ravenous Gigantotherium", power=3, toughness=3)
    one = obj(eng, "One", power=1, toughness=1, player="p2")
    two = obj(eng, "Two", power=2, toughness=2, player="p2")
    eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=source.instance_id,
                                   controller_id="p1"))
    eng.resolve_until_stable()
    eng.resolve_pending_choice(str(one.instance_id))
    eng.resolve_pending_choice(str(two.instance_id))
    if eng.state.pending_choice["kind"] != "trigger_damage_division":
        eng.resolve_pending_choice("stop")
    assert eng.state.pending_choice["kind"] == "trigger_damage_division"
    eng.rules.resolve_choice("1")
    assert eng.state.stack[-1].effects[0].division == [1, 2]
    source.counters["+1/+1"] = 10
    eng.resolve_until_stable()
    assert one.zone == two.zone == Zone.GRAVEYARD
    assert source.damage_marked == 3
    damage = [event for event in eng.state.event_log if event.type == EventType.DAMAGE]
    assert [event.get("amount") for event in damage] == [1, 2, 1, 2]


def test_ravenous_zero_targets_deals_no_damage():
    eng = engine()
    source = obj(eng, "Ravenous Gigantotherium", power=3, toughness=3)
    obj(eng, "Opponent", power=2, toughness=2, player="p2")
    eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=source.instance_id,
                                   controller_id="p1"))
    eng.resolve_until_stable()
    eng.resolve_pending_choice("stop")
    eng.resolve_until_stable()
    assert source.zone == Zone.BATTLEFIELD and source.damage_marked == 0
    assert not [event for event in eng.state.event_log if event.type == EventType.DAMAGE]


def test_ravenous_devour_counters_are_present_before_target_announcement():
    eng = engine()
    eng.state.current_step = "main1"
    fodder = obj(eng, "Fodder", power=1, toughness=1)
    source = obj(eng, "Ravenous Gigantotherium", zone=Zone.HAND, power=3, toughness=3)
    eng.cast_spell(eng.state.players[0], source)
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "choose_objects"
    eng.resolve_pending_choice(str(fodder.instance_id))
    eng.recompute_continuous_effects()
    assert source.zone == Zone.BATTLEFIELD and fodder.zone == Zone.GRAVEYARD
    assert source.counters["+1/+1"] == 3 and source.power == 6
    assert eng.state.pending_choice["kind"] == "trigger_target_multi"
    eng.resolve_pending_choice("stop")
    eng.resolve_until_stable()


def test_ravenous_clone_during_division_keeps_the_remaining_trigger_queue():
    from mtg_analyzer.game.effects.core import TriggeredAbility
    from mtg_analyzer.game.effects.life_sacrifice import GainLifeEffect

    eng = engine()
    source = obj(eng, "Ravenous Gigantotherium", power=3, toughness=3)
    one = obj(eng, "One", power=1, toughness=1, player="p2")
    two = obj(eng, "Two", power=2, toughness=2, player="p2")
    event = GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=source.instance_id, controller_id="p1")
    eng.state.fire_event(event)
    eng.rules.pending_triggers.append((TriggeredAbility(EventType.ENTERS_BATTLEFIELD,
        [GainLifeEffect(amount=5, source=source)], source=source, controller_id="p1"), event))
    eng.resolve_until_stable()
    eng.rules.resolve_choice(str(one.instance_id))
    eng.rules.resolve_choice(str(two.instance_id))
    eng.rules.resolve_choice("stop")
    assert eng.state.pending_choice["kind"] == "trigger_damage_division"
    cloned = GameEngine(eng.state.clone())
    cloned.rules.resolve_choice("1")
    assert len(cloned.state.stack) == 2
    cloned.resolve_until_stable()
    assert cloned.state.players[0].life == 45


def test_ravenous_uses_last_known_power_if_source_dies_before_placement():
    eng = engine()
    source = obj(eng, "Ravenous Gigantotherium", power=3, toughness=3)
    source.counters["+1/+1"] = 3
    target = obj(eng, "Target", power=5, toughness=5, player="p2")
    eng.recompute_continuous_effects()
    eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=source.instance_id,
                                   controller_id="p1"))
    eng.rules.destroy(source)
    eng.resolve_until_stable()
    eng.rules.resolve_choice(str(target.instance_id))
    if eng.state.pending_choice:
        eng.rules.resolve_choice("stop")
    eng.resolve_until_stable()
    assert target.zone == Zone.GRAVEYARD
    damage = [event for event in eng.state.event_log if event.type == EventType.DAMAGE]
    assert [event.get("amount") for event in damage] == [6]

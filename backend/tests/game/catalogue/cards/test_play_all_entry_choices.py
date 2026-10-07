"""Choices made as a permanent enters, with stable pending-entry identities."""
import json
import pytest

from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import RICH, card, filler, game, main_phase


def _sin_board():
    engine = game()
    ally = filler(engine, "Ally", power=2, toughness=2)
    ally.counters["+1/+1"] = 2
    enemy = filler(engine, "Enemy", player="p2", power=2, toughness=2)
    enemy.counters["shield"] = 1
    land = card(engine, "Forest")
    land.counters["charge"] = 7
    sin = card(engine, "Sin, Unending Cataclysm", zone=Zone.HAND)
    me = engine.state.player_by_id("p1")
    me.mana_pool.add_many(RICH)
    main_phase(engine)
    engine.cast_spell(me, sin)
    engine.resolve_until_stable()
    return engine, sin, ally, enemy, land


def test_sin_selects_a_subset_before_any_selected_counters_are_removed():
    engine, sin, ally, enemy, land = _sin_board()
    assert sin.zone == Zone.STACK and sin not in engine.state.battlefield
    options = engine.state.pending_choice["options"]
    assert land.instance_id not in {o.get("instance_id") for o in options}
    engine.resolve_pending_choice(str(enemy.instance_id))
    assert enemy.counters["shield"] == 1 and sin.zone == Zone.STACK
    engine.resolve_pending_choice("decline")
    assert not enemy.counters and ally.counters["+1/+1"] == 2 and land.counters["charge"] == 7
    assert sin.counters["+1/+1"] == 2 and engine.state.pending_permanent_entry is None


def test_sin_can_remove_no_counters():
    engine, sin, ally, enemy, land = _sin_board()
    engine.rules.resolve_choice("decline")
    assert ally.counters["+1/+1"] == 2 and enemy.counters["shield"] == 1
    assert land.counters["charge"] == 7 and sin.counters.get("+1/+1", 0) == 0


def test_sin_choice_survives_a_session_rollback_and_remains_json_serializable():
    from mtg_analyzer.services.game_session import GameSession, GameActionError
    engine, sin, ally, enemy, _ = _sin_board()
    session = GameSession(engine)
    json.dumps(session.view())
    with pytest.raises(GameActionError):
        session.apply_action({"type": "choose", "option_id": "999999"})
    session.apply_action({"type": "choose", "option_id": str(ally.instance_id)})
    session.apply_action({"type": "choose", "option_id": "decline"})
    restored = session.engine.state.find_object(sin.instance_id)
    assert restored.zone == Zone.BATTLEFIELD and restored.counters["+1/+1"] == 4
    assert session.engine.state.find_object(enemy.instance_id).counters["shield"] == 1
    json.dumps(session.view())


def test_dermotaxi_imprints_before_its_entry_event_with_no_imprint_trigger_on_the_stack():
    engine = game()
    taxi = card(engine, "Dermotaxi", zone=Zone.HAND)
    corpse = card(engine, "Llanowar Elves", player="p2", zone=Zone.GRAVEYARD)
    card(engine, "Elvish Mystic", zone=Zone.GRAVEYARD)
    me = engine.state.player_by_id("p1")
    me.mana_pool.add_many({"C": 2})
    main_phase(engine)
    observed = []
    engine.state.subscribe(lambda event: observed.append(taxi.linked_exile_id)
                           if event.type == EventType.ENTERS_BATTLEFIELD
                           and event.get("instance_id") == taxi.instance_id else None)
    engine.cast_spell(me, taxi)
    engine.resolve_until_stable()
    assert taxi not in engine.state.battlefield and observed == []
    assert engine.state.pending_choice["entry_effect"]
    engine.resolve_pending_choice(str(corpse.instance_id))
    assert taxi.zone == Zone.BATTLEFIELD and corpse.zone == Zone.EXILE
    assert observed == [corpse.instance_id] and not engine.state.stack


def test_before_entry_imprint_also_works_through_a_revealed_permanent_batch():
    engine = game()
    bridge = card(engine, "Esika, God of the Tree")
    engine.rules.switch_to_face(bridge, bridge.card.back_face())
    # A Clone entering as Dermotaxi inherits its before-entry imprint instruction.
    template = card(engine, "Dermotaxi")
    from mtg_analyzer.game.effects.core import EffectRegistry
    animation = EffectRegistry.create("grant_until", {
        "target_kind": "permanent",
        "static": {"type": "type_change", "params": {"add_types": ["creature"]}},
        "extra_statics": [{"type": "pt_set", "params": {"power": 2, "toughness": 2}}],
    })
    animation.source = bridge
    animation.apply(engine.rules.context, [template])
    assert template.is_creature
    corpse = card(engine, "Llanowar Elves", zone=Zone.GRAVEYARD)
    card(engine, "Elvish Mystic", zone=Zone.GRAVEYARD)
    clone = card(engine, "Clone", zone=Zone.LIBRARY)
    from tests.support.deck_batch import step, stack_library
    stack_library(engine, "p1", clone)
    step(engine, "upkeep")
    engine.resolve_pending_choice(str(template.instance_id))
    assert engine.state.pending_choice["entry_effect"]
    engine.resolve_pending_choice(str(corpse.instance_id))
    assert clone.zone == Zone.BATTLEFIELD and clone.linked_exile_id == corpse.instance_id


def test_excess_damage_tally_survives_a_nested_composition_branch():
    from mtg_analyzer.game.effects.core import EffectRegistry
    engine = game()
    source = filler(engine, "Source", power=2, toughness=2)
    victim = filler(engine, "Victim", player="p2", power=2, toughness=4)
    effect = EffectRegistry.create("seq", {"effects": [
        {"type": "damage", "params": {"amount": 6, "target_kind": "creature"}},
        {"type": "if_else", "params": {
            "condition": {"kind": "your_turn"},
            "then": [{"type": "gain_life", "params": {
                "amount": {"kind": "this_way", "tally": "excess_damage_this_way"},
            }}],
        }},
    ]})
    effect.source = source
    effect.apply(engine.rules.context, [victim])
    assert engine.state.player_by_id("p1").life == 22

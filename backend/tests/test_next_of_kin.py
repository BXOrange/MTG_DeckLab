"""Next of Kin's real death, untargeted choice and delayed Aura entry."""
import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _game, _card, _end_step
from tests.support.catalogue import battlefield_object


def _position(zone=Zone.HAND):
    engine = _game()
    aura = _card(engine, "Next of Kin")
    host = battlefield_object(engine, "p2", "Four mana host", "Creature", is_creature=True,
                              power=2, toughness=2, converted_mana_cost=4)
    aura.attached_to = host.instance_id
    small = _card(engine, "Llanowar Elves", zone=zone)
    equal = _card(engine, "Solemn Simulacrum", zone=Zone.HAND)
    land = _card(engine, "Forest", zone=Zone.HAND)
    engine.rules.destroy(host)
    engine.resolve_until_stable()
    return engine, aura, host, small, equal, land


@pytest.mark.parametrize("zone", [Zone.HAND, Zone.COMMAND])
def test_choice_puts_owned_lesser_creature_then_returns_aura_attached(zone):
    engine, aura, host, small, equal, land = _position(zone)
    choice = engine.state.pending_choice
    assert choice["kind"] == "choose_objects"
    assert {o["instance_id"] for o in choice["options"] if "instance_id" in o} == {small.instance_id}
    assert aura.zone == Zone.GRAVEYARD and host.zone == Zone.GRAVEYARD
    engine.resolve_pending_choice(small.instance_id)
    assert small.zone == Zone.BATTLEFIELD and small.controller_id == "p1"
    assert small not in getattr(engine.state.player_by_id("p1"), zone.value)
    assert aura.zone == Zone.GRAVEYARD
    assert len(engine.state.delayed_triggers) == 1
    _end_step(engine)
    engine.resolve_until_stable()
    assert aura.zone == Zone.BATTLEFIELD and aura.attached_to == small.instance_id
    assert equal.zone == Zone.HAND and land.zone == Zone.HAND


def test_declining_does_not_create_a_delayed_return():
    engine, aura, _, small, _, _ = _position()
    engine.resolve_pending_choice(None)
    assert small.zone == Zone.HAND
    assert not engine.state.delayed_triggers
    _end_step(engine)
    engine.resolve_until_stable()
    assert aura.zone == Zone.GRAVEYARD


@pytest.mark.parametrize("change", ["dies", "returns", "protection", "aura_exiled"])
def test_delayed_return_requires_original_host_and_aura(change):
    engine, aura, _, small, _, _ = _position()
    engine.resolve_pending_choice(small.instance_id)
    if change in {"dies", "returns"}:
        engine.rules.destroy(small)
        if change == "returns":
            engine.rules.return_from_graveyard(small)
    elif change == "protection":
        small.temp_protections.add("G")
        engine.recompute_continuous_effects()
    else:
        engine.rules.exile(aura)
    _end_step(engine)
    engine.resolve_until_stable()
    assert aura.zone == (Zone.EXILE if change == "aura_exiled" else Zone.GRAVEYARD)


def test_specs_are_fresh_and_enchant_is_preserved():
    engine = _game()
    aura = _card(engine, "Next of Kin")
    first, second = specs_for(aura.card), specs_for(aura.card)
    first[0].effects[0].params["pool_zones"].append("exile")
    assert second[0].effects[0].params["pool_zones"] == ["hand", "command"]
    assert aura.parametric_keywords["enchant"]["quality"] == "creature"
    assert len(aura.triggered_abilities) == 1


def test_empty_pool_and_zero_mana_value_host_offer_no_creature():
    engine = _game()
    aura = _card(engine, "Next of Kin")
    host = battlefield_object(engine, "p1", "Free host", "Creature", is_creature=True,
                              power=1, toughness=1, converted_mana_cost=0)
    aura.attached_to = host.instance_id
    _card(engine, "Llanowar Elves", zone=Zone.HAND)
    engine.rules.destroy(host)
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None
    assert not engine.state.delayed_triggers
    assert aura.zone == Zone.GRAVEYARD


def test_returned_aura_uses_ability_controller_even_with_different_owner():
    engine = _game()
    aura = _card(engine, "Next of Kin", player="p2")
    aura.controller_id = "p1"
    host = battlefield_object(engine, "p1", "Host", "Creature", is_creature=True,
                              power=2, toughness=2, converted_mana_cost=4)
    aura.attached_to = host.instance_id
    small = _card(engine, "Llanowar Elves", zone=Zone.HAND)
    engine.rules.destroy(host)
    engine.resolve_until_stable()
    assert engine.state.pending_choice["player_id"] == "p1"
    engine.resolve_pending_choice(small.instance_id)
    _end_step(engine)
    engine.resolve_until_stable()
    assert aura.owner_id == "p2" and aura.controller_id == "p1"
    assert aura.attached_to == small.instance_id


def test_delayed_return_is_a_respondable_stack_ability():
    engine, aura, _, small, _, _ = _position()
    engine.resolve_pending_choice(small.instance_id)
    engine._fire_delayed_triggers("end")
    assert aura.zone == Zone.GRAVEYARD
    assert engine.state.stack
    engine.rules.destroy(small)
    engine.resolve_until_stable()
    assert aura.zone == Zone.GRAVEYARD


def test_dies_mana_value_is_last_known_even_after_host_returns():
    engine, aura, host, small, _, _ = _position()
    # The trigger's saved value remains four even if that object changes.
    event = next(e for e in reversed(engine.state.event_log)
                 if e.type == EventType.DIES and e.get("instance_id") == host.instance_id)
    assert event.get("mana_value") == 4
    engine.rules.return_from_graveyard(host)
    engine.resolve_pending_choice(small.instance_id)
    _end_step(engine)
    engine.resolve_until_stable()
    assert aura.attached_to == small.instance_id


def test_hand_and_command_cards_are_offered_together_without_targeting():
    engine = _game()
    aura = _card(engine, "Next of Kin")
    host = battlefield_object(engine, "p1", "Host", "Creature", is_creature=True,
                              power=2, toughness=2, converted_mana_cost=4)
    aura.attached_to = host.instance_id
    hand = _card(engine, "Llanowar Elves", zone=Zone.HAND)
    commander = _card(engine, "Elvish Mystic", zone=Zone.COMMAND)
    foreign = _card(engine, "Birds of Paradise", player="p2", zone=Zone.COMMAND)
    engine.rules.destroy(host)
    engine.resolve_until_stable()
    assert {o["instance_id"] for o in engine.state.pending_choice["options"]
            if "instance_id" in o} == {hand.instance_id, commander.instance_id}
    engine.resolve_pending_choice(commander.instance_id)
    commander.temp_keywords.add("hexproof")
    seen = []
    engine.state.subscribe(lambda event: seen.append(aura.attached_to)
                           if event.type == EventType.ENTERS_BATTLEFIELD
                           and event.get("instance_id") == aura.instance_id else None)
    _end_step(engine)
    engine.resolve_until_stable()
    assert seen == [commander.instance_id]  # already attached as it enters
    assert aura.attached_to == commander.instance_id
    assert foreign.zone == Zone.COMMAND and hand.zone == Zone.HAND

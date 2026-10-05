"""Actual Hideaway land entry and conditional activation resolution."""

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import specs_for, is_registered
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase
from tests.test_hideaway_keyword import _game


@pytest.mark.parametrize("name", ["Mosswort Bridge", "Spinerock Knoll"])
def test_hideaway_land_specs_are_fresh_and_bind_with_the_keyword(name):
    card = CardDatabase(DB_PATH).get_card(name)
    assert is_registered(name)
    first = specs_for(card)
    activated = next(spec for spec in first if spec.ability_kind == "activated")
    activated.effects[0].params["condition"]["min"] = 999
    second = specs_for(card)
    assert next(spec for spec in second if spec.ability_kind == "activated").effects[0].params["condition"]["min"] in (7, 10)
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    assert len(obj.triggered_abilities) == len(obj.activated_abilities) == 1
    assert obj.activated_abilities[0].taps_source


def _land_game(name, color, damage=7):
    engine, player, old_land, cards = _game(available=8)
    player.hand.remove(old_land)
    land = GameObject(CardDatabase(DB_PATH).get_card(name), owner_id=player.id, zone=Zone.HAND)
    bind_from_catalogue(land)
    player.add_to_zone(land, Zone.HAND)
    hidden = cards[-1]
    hidden.card = CardDatabase(DB_PATH).get_card("Lightning Bolt")
    bind_from_catalogue(hidden)
    engine.play_land(player, land)
    assert land.tapped
    engine.resolve_until_stable()
    engine.resolve_pending_choice(str(hidden.instance_id))
    assert hidden in player.exile and hidden.face_down_in_exile
    assert len(land.activated_abilities) == 1
    creature = GameObject(Card(id="power", name="Power", type_line="Creature", is_creature=True,
                               power=10, toughness=10), owner_id=player.id, zone=Zone.BATTLEFIELD)
    engine.state.add_to_battlefield(creature)
    engine.rules.deal_damage(engine.state.player_by_id("p2"), damage)
    land.tapped = False
    engine.tap_for_mana(player, land)
    assert player.mana_pool.pool.get(color) == 1
    land.tapped = False
    return engine, player, land, hidden, creature


@pytest.fixture(params=[("Mosswort Bridge", "G"), ("Spinerock Knoll", "R")])
def land_game(request):
    return _land_game(*request.param)


def test_real_hideaway_activation_casts_selected_spell(land_game):
    engine, player, land, hidden, _ = land_game
    engine.activate_ability(player, land, 0)
    assert land.tapped and player.mana_pool.total() == 0
    engine.rules.resolve_top_of_stack()
    assert engine.state.pending_choice["kind"] == "play_during_resolution"
    victim = engine.state.player_by_id("p3")
    engine.play_resolution_card(player, hidden, targets=[victim])
    assert hidden.zone == Zone.STACK
    engine.rules.resolve_top_of_stack()
    assert victim.life == 17


def test_real_hideaway_activation_survives_source_removal(land_game):
    engine, player, land, hidden, _ = land_game
    engine.activate_ability(player, land, 0)
    engine.rules.return_to_hand(land)
    assert not land.hideaway_exile_ids
    engine.rules.resolve_top_of_stack()
    assert engine.state.pending_choice["instance_ids"] == [hidden.instance_id]
    engine.play_resolution_card(player, hidden, targets=[engine.state.player_by_id("p3")])
    assert hidden.zone == Zone.STACK


def test_real_hideaway_activation_can_be_declined(land_game):
    engine, player, land, hidden, _ = land_game
    engine.activate_ability(player, land, 0)
    engine.rules.resolve_top_of_stack()
    engine.rules.resolve_choice("decline")
    assert hidden.zone == Zone.EXILE
    assert not engine.can_cast(player, hidden)


def test_mosswort_condition_is_checked_at_resolution():
    engine, player, land, hidden, creature = _land_game("Mosswort Bridge", "G")
    engine.activate_ability(player, land, 0)
    engine.rules.return_to_hand(creature)
    engine.rules.resolve_top_of_stack()
    assert not engine.state.pending_choice
    assert hidden.zone == Zone.EXILE


@pytest.mark.parametrize("name,color", [("Mosswort Bridge", "G"), ("Spinerock Knoll", "R")])
def test_condition_may_become_true_after_activation(name, color):
    engine, player, land, hidden, creature = _land_game(name, color, damage=6)
    creature.card.power = 9
    engine.recompute_continuous_effects()
    engine.activate_ability(player, land, 0)
    creature.card.power = 10
    engine.recompute_continuous_effects()
    engine.rules.deal_damage(engine.state.player_by_id("p2"), 1)
    engine.rules.resolve_top_of_stack()
    assert engine.state.pending_choice["instance_ids"] == [hidden.instance_id]


def test_spinerock_life_loss_is_not_the_damage_condition():
    engine, player, land, hidden, _ = _land_game("Spinerock Knoll", "R", damage=6)
    engine.rules.lose_life(engine.state.player_by_id("p2"), 1)
    engine.activate_ability(player, land, 0)
    engine.rules.resolve_top_of_stack()
    assert not engine.state.pending_choice and hidden.zone == Zone.EXILE


def test_hideaway_activation_ignores_cards_no_longer_in_exile(land_game):
    engine, player, land, hidden, _ = land_game
    engine.activate_ability(player, land, 0)
    engine.rules.return_to_hand(hidden)
    engine.rules.resolve_top_of_stack()
    assert not engine.state.pending_choice


def test_card_leaving_exile_and_returning_is_not_the_old_linked_card(land_game):
    engine, player, land, hidden, _ = land_game
    engine.activate_ability(player, land, 0)
    engine.rules.return_to_hand(hidden)
    engine.rules.exile(hidden)
    engine.rules.resolve_top_of_stack()
    assert hidden.zone == Zone.EXILE and not engine.state.pending_choice


def test_old_activation_does_not_play_a_new_exile_of_same_card_by_same_source(land_game):
    from mtg_analyzer.models.game.events import EventType, GameEvent

    engine, player, land, hidden, _ = land_game
    engine.activate_ability(player, land, 0)
    engine.rules.return_to_library(hidden)
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD,
                                     instance_id=land.instance_id, controller_id=player.id))
    engine.rules.put_triggers_on_stack()
    engine.rules.resolve_top_of_stack()
    engine.rules.resolve_choice(str(hidden.instance_id))
    while engine.rules.resume_deferred_effects():
        pass
    assert hidden.zone == Zone.EXILE and hidden.hideaway_source_id == land.instance_id
    engine.rules.resolve_top_of_stack()
    assert not engine.state.pending_choice


def test_activation_keeps_its_controller_after_land_returns_to_owner(land_game):
    engine, owner, land, hidden, creature = land_game
    caster = engine.state.player_by_id("p2")
    land.controller_id = caster.id
    creature.controller_id = caster.id
    engine.recompute_continuous_effects()
    engine.rules.deal_damage(engine.state.player_by_id("p3"), 7)
    caster.mana_pool.add("G" if land.name == "Mosswort Bridge" else "R", 1)
    engine.activate_ability(caster, land, 0)
    engine.rules.return_to_hand(land)
    assert land.controller_id == owner.id
    engine.rules.resolve_top_of_stack()
    assert engine.state.pending_choice["player_id"] == caster.id
    victim = engine.state.player_by_id("p3")
    engine.play_resolution_card(caster, hidden, targets=[victim])
    assert hidden.controller_id == caster.id and hidden.owner_id == owner.id
    engine.rules.resolve_top_of_stack()
    assert victim.life == 10


def test_hideaway_activation_does_not_allow_a_second_land_play(land_game):
    engine, player, land, hidden, _ = land_game
    hidden.card = CardDatabase(DB_PATH).get_card("Forest")
    engine.activate_ability(player, land, 0)
    engine.rules.resolve_top_of_stack()
    assert not engine.can_play_land(player, hidden)
    with pytest.raises(ValueError):
        engine.play_resolution_card(player, hidden)
    assert hidden.zone == Zone.EXILE
    engine.rules.resolve_choice("decline")


def test_hideaway_activation_preserves_modal_spell_choice(land_game):
    engine, player, land, hidden, _ = land_game
    hidden.card = CardDatabase(DB_PATH).get_card("Abzan Charm")
    hidden.spell_effects.clear()
    bind_from_catalogue(hidden)
    engine.activate_ability(player, land, 0)
    engine.rules.resolve_top_of_stack()
    before = len(player.hand)
    engine.play_resolution_card(player, hidden, mode=1)
    engine.rules.resolve_top_of_stack()
    assert len(player.hand) == before + 2
    assert player.life == 18


def test_one_activation_may_play_each_card_linked_by_duplicate_hideaway(land_game):
    from mtg_analyzer.models.game.events import EventType, GameEvent

    engine, player, land, first, _ = land_game
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD,
                                     instance_id=land.instance_id, controller_id=player.id))
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    second_id = choice["options"][0]["instance_id"]
    second = engine.state.find_object(second_id)
    second.card = CardDatabase(DB_PATH).get_card("Lightning Bolt")
    bind_from_catalogue(second)
    engine.resolve_pending_choice(str(second_id))
    assert land.hideaway_exile_ids == {first.instance_id, second_id}
    engine.activate_ability(player, land, 0)
    engine.rules.resolve_top_of_stack()
    victim = engine.state.player_by_id("p3")
    engine.play_resolution_card(player, first, targets=[victim])
    assert victim.life == 20 and engine.state.pending_choice is not None
    engine.play_resolution_card(player, second, targets=[victim])
    assert not engine.state.pending_choice
    assert not engine.state.resolution_play_waiting
    assert first.zone == second.zone == Zone.STACK
    engine.rules.resolve_top_of_stack()
    engine.rules.resolve_top_of_stack()
    assert victim.life == 14

"""RULE 608.2g / 305.2–3: playing a card while an effect resolves."""

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import GameEffect
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import StackItem
from mtg_analyzer.services.card_database import CardDatabase
from tests.test_hideaway_keyword import _game


def _offer(name, *, controller="p1", owner="p1"):
    engine, _, _, _ = _game(available=8)
    player = engine.state.player_by_id(controller)
    card = CardDatabase(DB_PATH).get_card(name)
    assert card is not None
    obj = GameObject(card, owner_id=owner, zone=Zone.EXILE)
    bind_from_catalogue(obj)
    engine.state.player_by_id(owner).add_to_zone(obj, Zone.EXILE)
    obj.face_down_in_exile = True
    engine.state.stack.append(StackItem(kind="ability", controller_id="p1", effects=[]))
    engine.rules._request_resolution_play(player, [obj])
    return engine, player, obj


def test_resolution_spell_keeps_targets_and_waits_for_priority():
    engine, player, spell = _offer("Lightning Bolt", controller="p2", owner="p1")
    victim = engine.state.player_by_id("p3")
    engine.play_resolution_card(player, spell, targets=[victim])
    assert spell.zone == Zone.STACK and spell.controller_id == player.id
    assert not spell.face_down_in_exile
    assert spell not in engine.state.player_by_id("p1").exile
    assert victim.life == 20  # No automatic resolution of the nested spell.
    assert not engine.state.pending_choice and not engine.state.resolution_play_choice
    assert spell.instance_id not in engine.state.free_cast_instance_ids
    engine.rules.resolve_top_of_stack()
    assert victim.life == 17


def test_resolution_sorcery_does_not_need_an_empty_stack_or_active_turn():
    engine, player, spell = _offer("Divination", controller="p2")
    before = len(player.hand)
    engine.play_resolution_card(player, spell)
    assert spell.zone == Zone.STACK
    engine.rules.resolve_top_of_stack()
    assert len(player.hand) == before + 2


def test_decline_revokes_the_permission_and_preserves_other_free_casts():
    engine, player, spell = _offer("Divination")
    engine.state.free_cast_instance_ids.add(1234567)
    engine.rules.resolve_choice("decline")
    assert spell.zone == Zone.EXILE
    assert not engine.can_cast(player, spell)
    assert not engine.state.resolution_play_choice
    assert engine.state.free_cast_instance_ids == {1234567}
    assert not engine.state.free_cast_ignore_timing_instance_ids


def test_invalid_target_keeps_resolution_choice_available():
    engine, player, spell = _offer("Lightning Bolt")
    with pytest.raises(ValueError):
        engine.play_resolution_card(player, spell, targets=[])
    assert engine.state.pending_choice["kind"] == "play_during_resolution"
    assert spell.zone == Zone.EXILE
    engine.play_resolution_card(player, spell, targets=[engine.state.player_by_id("p2")])
    assert spell.zone == Zone.STACK


@pytest.mark.parametrize("controller, lands_played, legal", [
    ("p1", 0, True), ("p1", 1, False), ("p2", 0, False),
])
def test_resolution_land_obeys_turn_and_land_limit(controller, lands_played, legal):
    engine, player, land = _offer("Forest", controller=controller, owner="p2")
    player.lands_played_this_turn = lands_played
    assert engine.can_play_land(player, land) is legal
    if legal:
        engine.play_resolution_card(player, land)
        assert land in engine.state.battlefield
        assert land.controller_id == player.id
        assert land not in engine.state.player_by_id("p2").exile
        assert player.lands_played_this_turn == 1
    else:
        with pytest.raises(ValueError):
            engine.play_resolution_card(player, land)
        assert land.zone == Zone.EXILE
        engine.rules.resolve_choice("decline")


def test_resolution_free_cast_rejects_alternative_costs_and_nonzero_x():
    engine, player, spell = _offer("Fireball")
    for options in ({"alt_cost": True}, {"evoke": True}, {"x": 3}):
        with pytest.raises(ValueError):
            engine.play_resolution_card(player, spell, **options)
        assert engine.state.pending_choice is not None
    engine.play_resolution_card(player, spell, x=0, targets=[engine.state.player_by_id("p2")])
    assert spell.zone == Zone.STACK


def test_resolution_permission_is_restricted_to_offered_card_and_player():
    engine, player, spell = _offer("Lightning Bolt")
    with pytest.raises(ValueError):
        engine.play_resolution_card(engine.state.player_by_id("p2"), spell)
    with pytest.raises(ValueError):
        engine.play_resolution_card(player, player.hand[0])
    with pytest.raises(ValueError):
        engine.play_resolution_card(player, spell, face="back")
    with pytest.raises(ValueError):
        engine.rules.resolve_choice("cast")
    assert engine.state.pending_choice["kind"] == "play_during_resolution"


def test_resolution_modal_spell_uses_the_announced_mode():
    engine, player, spell = _offer("Abzan Charm")
    assert len(spell.spell_modes) == 3
    before = len(player.hand)
    engine.play_resolution_card(player, spell, mode=1)
    engine.rules.resolve_top_of_stack()
    assert len(player.hand) == before + 2
    assert player.life == 18


def test_resolution_free_cast_still_pays_multikicker():
    engine, player, spell = _offer("Everflowing Chalice")
    with pytest.raises(ValueError):
        engine.play_resolution_card(player, spell, kicked=1)
    player.mana_pool.add("C", 2)
    engine.play_resolution_card(player, spell, kicked=1)
    assert spell.mana_spent_to_cast == 2
    assert player.mana_pool.total() == 0
    engine.rules.resolve_top_of_stack()
    assert spell.counters.get("charge") == 1


def test_resolution_finishes_outer_effect_before_nested_spell_resolves():
    from mtg_analyzer.game.effects.life_sacrifice import GainLifeEffect

    engine, player, spell = _offer("Lightning Bolt")
    engine.rules.resolve_choice("decline")

    class Offer(GameEffect):
        def apply(self, context, targets=None):
            context.offer_play_during_resolution(player, [spell])

    engine.state.stack.append(StackItem(kind="ability", controller_id=player.id,
                                       effects=[Offer(), GainLifeEffect(4)]))
    engine.rules.resolve_top_of_stack()
    assert engine.state.pending_choice is not None
    assert engine.state.deferred_effects
    assert player.life == 20
    victim = engine.state.player_by_id("p2")
    engine.play_resolution_card(player, spell, targets=[victim])
    assert player.life == 24 and victim.life == 20
    assert not engine.state.deferred_effects
    engine.rules.resolve_top_of_stack()
    assert victim.life == 17


def test_session_exposes_resolution_cast_targets_and_accepts_the_action():
    from mtg_analyzer.services.game_session import GameSession, GameActionError, MULTIPLAYER

    engine, player, spell = _offer("Lightning Bolt", controller="p2")
    session = GameSession(engine, mode=MULTIPLAYER, mulligan_style="none")
    session._setup_pending.clear()
    view = session.view(perspective=player.id)
    offers = [a for a in view["legal_actions"] if a["type"] == "cast_spell"]
    assert len(offers) == 1 and offers[0]["instance_id"] == spell.instance_id
    assert offers[0]["targets"][0]["options"]
    assert any(opt.get("action", {}).get("type") == "cast_spell" for opt in view["pending_choice"]["options"])
    assert engine.state.pending_choice["options"] == [{"id": "decline", "label": "Decline"}]
    assert session.legal_actions("p3") == []
    with pytest.raises(GameActionError):
        session.apply_action({"type": "cast_spell", "instance_id": spell.instance_id,
                              "targets": [{"player_id": "p3"}]}, actor_id="p3")
    with pytest.raises(GameActionError):
        session.apply_action({"type": "decline"}, actor_id="p3")
    session.apply_action({"type": "cast_spell", "instance_id": spell.instance_id,
                          "targets": [{"player_id": "p3"}]}, actor_id=player.id)
    assert engine.state.find_object(spell.instance_id).zone == Zone.STACK
    assert engine.state.priority_player.id == engine.state.active_player.id


def test_session_resolution_land_offer_and_decline_only_for_other_turn():
    from mtg_analyzer.services.game_session import GameSession

    engine, player, land = _offer("Forest")
    session = GameSession(engine, mulligan_style="none")
    session._setup_pending.clear()
    offers = session.legal_actions(player.id)
    assert {a["type"] for a in offers} == {"decline", "play_land"}
    session.apply_action({"type": "play_land", "instance_id": land.instance_id}, actor_id=player.id)
    assert land in engine.state.battlefield


def test_interactive_decline_finishes_resolution_without_draining_other_stack_items():
    engine, player, spell = _offer("Divination", controller="p2")
    engine.interactive_priority = True
    lower_item = engine.state.stack[-1]
    engine.resolve_pending_choice("decline")
    assert engine.state.stack == [lower_item]
    assert spell.zone == Zone.EXILE and not engine.can_cast(player, spell)
    assert engine.state.priority_player is engine.state.active_player


def test_repeated_play_waits_for_a_lands_entry_choice_before_offering_next_card():
    engine, player, land = _offer("Forest")
    engine.rules.resolve_choice("decline")
    land.card = Card(id="choice-land", name="Choice Land", type_line="Land", is_land=True,
                     oracle_text="As Choice Land enters, choose a color.")
    bind_from_catalogue(land)
    assert land.enter_choice_effects
    spell = GameObject(CardDatabase(DB_PATH).get_card("Divination"), owner_id=player.id, zone=Zone.EXILE)
    bind_from_catalogue(spell)
    player.add_to_zone(spell, Zone.EXILE)
    engine.rules._request_resolution_play(player, [land, spell], repeat=True)
    engine.play_resolution_card(player, land)
    choice = engine.state.pending_choice
    assert choice is not None and choice["kind"] != "play_during_resolution"
    assert engine.state.resolution_play_followup is not None
    engine.resolve_pending_choice(choice["options"][0]["id"])
    assert land in engine.state.battlefield
    assert engine.state.pending_choice["instance_ids"] == [spell.instance_id]
    engine.play_resolution_card(player, spell)
    assert not engine.state.pending_choice and not engine.state.resolution_play_waiting
    assert spell.zone == Zone.STACK


def test_repeated_paid_offers_charge_each_spell_normally():
    engine, player, first = _offer("Divination")
    engine.rules.resolve_choice("decline")
    second = GameObject(CardDatabase(DB_PATH).get_card("Divination"), owner_id=player.id, zone=Zone.EXILE)
    bind_from_catalogue(second)
    player.add_to_zone(second, Zone.EXILE)
    player.mana_pool.add_many({"U": 2, "C": 4})
    engine.rules._request_resolution_play(player, [first, second], repeat=True, free=False)
    engine.play_resolution_card(player, first)
    assert first.mana_spent_to_cast == 3
    assert engine.state.pending_choice["free"] is False
    engine.play_resolution_card(player, second)
    assert second.mana_spent_to_cast == 3
    assert not engine.state.resolution_play_choice


def test_resolution_mana_wildcard_is_scoped_and_restores_an_unplayed_prior_permission():
    engine, player, spell = _offer("Divination")
    engine.rules.resolve_choice("decline")
    engine.state.mana_wildcard_permission[spell.instance_id] = "color"
    engine.rules._request_resolution_play(player, [spell], free=False, mana_wildcard="type")
    assert engine.state.mana_wildcard_permission[spell.instance_id] == "type"
    engine.rules.resolve_choice("decline")
    assert engine.state.mana_wildcard_permission[spell.instance_id] == "color"
    engine.rules._request_resolution_play(player, [spell], free=False, mana_wildcard="type")
    player.mana_pool.add_many({"R": 3})
    engine.play_resolution_card(player, spell)
    assert spell.mana_spent_to_cast == 3
    assert spell.instance_id not in engine.state.mana_wildcard_permission


def test_paid_resolution_offer_can_use_an_ordinary_alternative_cost():
    engine, player, spell = _offer("Snuff Out")
    engine.rules.resolve_choice("decline")
    swamp = GameObject(CardDatabase(DB_PATH).get_card("Swamp"), owner_id=player.id, zone=Zone.BATTLEFIELD)
    engine.state.add_to_battlefield(swamp)
    victim = GameObject(Card(id="victim", name="Victim", type_line="Creature", is_creature=True,
                             power=2, toughness=2), owner_id="p2", zone=Zone.BATTLEFIELD)
    engine.state.add_to_battlefield(victim)
    engine.rules._request_resolution_play(player, [spell], only_spells=True, free=False)
    assert any(a.get("alt_cost") for a in engine.resolution_play_actions(player))
    engine.play_resolution_card(player, spell, targets=[victim], alt_cost=True)
    assert player.life == 16 and spell.zone == Zone.STACK

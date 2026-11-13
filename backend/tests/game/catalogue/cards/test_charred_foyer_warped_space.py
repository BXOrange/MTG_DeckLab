"""Charred Foyer play permission and Warped Space's once-per-turn alternative cost."""
from mtg_analyzer.game import rooms
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import RICH, card, cast, filler, game


NAME = "Charred Foyer // Warped Space"


def _board():
    engine = game()
    player = engine.state.player_by_id("p1")
    source = card(engine, NAME, zone=Zone.HAND)
    cast(engine, source, face="back")
    player.mana_pool.empty()
    return engine, player, source


def _exiled(engine, player, name="Grizzly Bears"):
    obj = card(engine, name, zone=Zone.EXILE)
    engine.rules._grant_temp_play_permission(obj, player, "Test permission", False, None)
    return obj


def test_charred_foyer_upkeep_grants_play_permission_then_warped_space_casts_free():
    engine = game()
    player = engine.state.player_by_id("p1")
    hit = card(engine, "Grizzly Bears", zone=Zone.LIBRARY)
    source = card(engine, NAME, zone=Zone.HAND)
    cast(engine, source)
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep"))
    engine.resolve_until_stable()
    assert hit.zone == Zone.EXILE
    player.mana_pool.add_many(RICH)
    engine.unlock_door(player, source, rooms.RIGHT)
    engine.resolve_until_stable()
    player.mana_pool.empty()
    engine.cast_spell(player, hit, alt_cost=True)
    engine.resolve_until_stable()
    assert hit.zone == Zone.BATTLEFIELD and player.mana_pool.total() == 0


def test_once_each_turn_limit_and_next_turn_reset():
    engine, player, source = _board()
    first, second = _exiled(engine, player), _exiled(engine, player)
    engine.cast_spell(player, first, alt_cost=True)
    engine.resolve_until_stable()
    assert not engine.can_cast(player, second, alt_cost=True)
    engine.state.internal_turn.number += 1
    assert engine.can_cast(player, second, alt_cost=True)
    engine.cast_spell(player, second, alt_cost=True)
    engine.resolve_until_stable()
    assert second.zone == Zone.BATTLEFIELD


def test_does_not_grant_permission_to_cast_an_arbitrary_exiled_card_or_hand_card():
    engine, player, source = _board()
    exiled = card(engine, "Grizzly Bears", zone=Zone.EXILE)
    hand = card(engine, "Grizzly Bears", zone=Zone.HAND)
    assert not engine.can_cast(player, exiled, alt_cost=True)
    assert not engine.can_cast(player, hand, alt_cost=True)


def test_paying_normal_cost_does_not_spend_the_free_cast():
    engine, player, source = _board()
    first, second = _exiled(engine, player), _exiled(engine, player)
    cast(engine, first)
    player.mana_pool.empty()
    assert engine.can_cast(player, second, alt_cost=True)
    engine.cast_spell(player, second, alt_cost=True)
    engine.resolve_until_stable()
    assert second.zone == Zone.BATTLEFIELD


def test_locking_removes_cost_option_and_reunlock_does_not_reset_usage():
    engine, player, source = _board()
    first, second = _exiled(engine, player), _exiled(engine, player)
    rooms.lock(engine.state, source, rooms.RIGHT)
    assert not engine.can_cast(player, first, alt_cost=True)
    rooms.unlock(engine.state, source, rooms.RIGHT)
    engine.cast_spell(player, first, alt_cost=True)
    engine.resolve_until_stable()
    rooms.lock(engine.state, source, rooms.RIGHT)
    rooms.unlock(engine.state, source, rooms.RIGHT)
    assert not engine.can_cast(player, second, alt_cost=True)


def test_source_new_zone_visit_has_a_new_once_per_turn_allowance():
    engine, player, source = _board()
    first, second = _exiled(engine, player), _exiled(engine, player)
    engine.cast_spell(player, first, alt_cost=True)
    engine.resolve_until_stable()
    engine.rules.exile(source)
    engine.rules.return_from_graveyard(source, "battlefield")
    rooms.set_designations(source, [rooms.RIGHT])
    assert engine.can_cast(player, second, alt_cost=True)


def test_clone_preserves_spent_allowance():
    engine, player, source = _board()
    first, second = _exiled(engine, player), _exiled(engine, player)
    engine.cast_spell(player, first, alt_cost=True)
    engine.resolve_until_stable()
    clone = GameEngine(engine.state.clone())
    assert not clone.can_cast(clone.state.player_by_id("p1"), clone.state.find_object(second.instance_id), alt_cost=True)


def test_zero_mana_cost_still_requires_additional_sacrifice_cost():
    engine, player, source = _board()
    spell = _exiled(engine, player, "Village Rites")
    assert not engine.can_cast(player, spell, alt_cost=True)
    victim = filler(engine, "Victim", power=2, toughness=2)
    engine.cast_spell(player, spell, alt_cost=True, sacrifice_choice=victim.instance_id)
    engine.resolve_until_stable()
    assert victim.zone == Zone.GRAVEYARD and len(player.hand) == 2


def test_legal_actions_offer_the_zero_mana_alternative():
    engine, player, source = _board()
    spell = _exiled(engine, player)
    offers = [action for action in engine.legal_actions(player)
              if action.get("type") == "cast_spell" and action.get("instance_id") == spell.instance_id]
    assert any(action.get("alt_cost") and not action.get("locked") for action in offers)


def test_allowance_is_available_on_an_opponents_turn_for_an_instant():
    engine, player, source = _board()
    spell = _exiled(engine, player, "Lightning Bolt")
    engine.state.active_player_index = 1
    engine.cast_spell(player, spell, alt_cost=True, targets=[engine.state.player_by_id("p2")])
    engine.resolve_until_stable()
    assert engine.state.player_by_id("p2").life == 17 and player.mana_pool.total() == 0


def test_two_warped_spaces_have_independent_allowances():
    engine, player, source = _board()
    other = card(engine, NAME)
    rooms.set_designations(other, [rooms.RIGHT])
    first, second, third = (_exiled(engine, player) for _ in range(3))
    engine.cast_spell(player, first, alt_cost=True)
    engine.resolve_until_stable()
    engine.cast_spell(player, second, alt_cost=True)
    engine.resolve_until_stable()
    assert not engine.can_cast(player, third, alt_cost=True)

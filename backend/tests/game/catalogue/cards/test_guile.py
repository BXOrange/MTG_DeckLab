"""Guile replaces controlled counters, offers one immediate play, and retains its other abilities."""
import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, main_phase, RICH
from tests.support.star_trek import advance_to


def _announce(engine, obj, targets=None):
    player = engine.state.player_by_id(obj.controller_id)
    main_phase(engine)
    player.mana_pool.add_many(RICH)
    engine.cast_spell(player, obj, targets=targets)


def _board(counter="Counterspell", guile=True, target_owner="p2", counter_owner="p1", spell="Grizzly Bears"):
    engine = game(library=20)
    player, opponent = engine.state.player_by_id("p1"), engine.state.player_by_id("p2")
    source = card(engine, "Guile") if guile else None
    engine.state.active_player_index = 0 if target_owner == "p1" else 1
    target = card(engine, spell, target_owner, Zone.HAND)
    _announce(engine, target)
    answer = card(engine, counter, counter_owner, Zone.HAND)
    _announce(engine, answer, targets=[target])
    return engine, source, player, opponent, target, answer


def _resolve_counter(engine):
    engine.rules.resolve_top_of_stack()


def test_complete_catalogue_is_fresh_valid_and_bound():
    engine, source, player, opponent, target, answer = _board()
    first, second = specs_for(source.card), specs_for(source.card)
    assert first is not second and all(a is not b for a, b in zip(first, second))
    assert [s.ability_kind for s in first] == ["static", "replacement", "triggered"]
    for spec in first:
        spec.validate()
    assert source.static_effects and len(source.replacement_effects) == len(source.triggered_abilities) == 1


def test_counter_is_replaced_with_exile_and_immediate_free_cast_under_guile_controller():
    engine, source, player, opponent, target, answer = _board()
    _resolve_counter(engine)
    assert target.zone == Zone.EXILE and target in opponent.exile and answer.zone == Zone.STACK
    assert engine.state.pending_choice["kind"] == "play_during_resolution"
    assert engine.state.pending_choice["player_id"] == "p1"
    assert not any(e.type == EventType.SPELL_COUNTERED for e in engine.state.events_this_turn())
    player.mana_pool.empty()
    engine.play_resolution_card(player, target)
    assert target.zone == Zone.STACK and target.controller_id == "p1" and target.owner_id == "p2"
    assert answer in player.graveyard
    engine.resolve_until_stable()
    assert target.zone == Zone.BATTLEFIELD and target.controller_id == "p1" and target.mana_spent_to_cast == 0
    assert not engine.state.free_cast_instance_ids


def test_decline_leaves_card_exiled_and_grants_no_later_cast_permission():
    engine, source, player, opponent, target, answer = _board()
    _resolve_counter(engine)
    engine.resolve_pending_choice("decline")
    assert target in opponent.exile and not engine.can_cast(player, target)
    assert not engine.state.free_cast_instance_ids and not engine.state.free_cast_ignore_timing_instance_ids
    assert not engine.state.pending_choice


def test_opponents_counter_is_not_replaced_by_your_guile():
    engine, source, player, opponent, target, answer = _board(target_owner="p1", counter_owner="p2")
    _resolve_counter(engine)
    assert target in player.graveyard and not engine.state.pending_choice
    counters = [e for e in engine.state.events_this_turn() if e.type == EventType.SPELL_COUNTERED]
    assert len(counters) == 1 and counters[0].get("controller_id") == "p2"


def test_guile_may_replace_a_counter_of_its_controllers_own_spell():
    engine, source, player, opponent, target, answer = _board(target_owner="p1")
    _resolve_counter(engine)
    assert target in player.exile and engine.state.pending_choice["player_id"] == "p1"
    engine.resolve_pending_choice("decline")


def test_a_spell_that_cannot_be_countered_is_not_exiled_or_offered():
    engine, source, player, opponent, target, answer = _board(spell="Supreme Verdict")
    _resolve_counter(engine)
    assert target.zone == Zone.STACK and not engine.state.pending_choice
    assert not any(e.type == EventType.SPELL_COUNTERED for e in engine.state.events_this_turn())


@pytest.mark.parametrize("pay", [False, True])
def test_unless_payment_is_decided_before_guile_replaces_the_counter(pay):
    engine, source, player, opponent, target, answer = _board(counter="Mana Leak")
    opponent.mana_pool.empty()
    opponent.mana_pool.add("C", 3)
    _resolve_counter(engine)
    assert engine.state.pending_choice["kind"] == "counter_unless_pays" and target.zone == Zone.STACK
    engine.resolve_pending_choice("pay" if pay else "decline")
    if pay:
        assert target.zone == Zone.BATTLEFIELD and not engine.state.pending_choice
    else:
        assert target.zone == Zone.EXILE and engine.state.pending_choice["kind"] == "play_during_resolution"


def test_live_replacement_is_lost_when_guile_leaves_before_counter_resolution():
    engine, source, player, opponent, target, answer = _board()
    engine.rules.exile(source)
    _resolve_counter(engine)
    assert target.zone == Zone.GRAVEYARD and not engine.state.pending_choice


def test_guile_entering_after_counter_was_cast_still_replaces_it():
    engine, source, player, opponent, target, answer = _board(guile=False)
    source = card(engine, "Guile")
    _resolve_counter(engine)
    assert target.zone == Zone.EXILE and engine.state.pending_choice["player_id"] == source.controller_id


def test_counter_with_illegal_target_has_nothing_for_guile_to_replace():
    engine, source, player, opponent, target, answer = _board()
    engine.rules.bounce_spell_or_permanent(target)
    _resolve_counter(engine)
    assert target in opponent.hand and not engine.state.pending_choice


def test_activated_counter_works_after_its_source_is_sacrificed_as_a_cost():
    engine = game()
    player, opponent = engine.state.player_by_id("p1"), engine.state.player_by_id("p2")
    source = card(engine, "Guile")
    apprentice = card(engine, "Daring Apprentice")
    target = card(engine, "Grizzly Bears", "p2", Zone.HAND)
    engine.state.active_player_index = 1
    _announce(engine, target)
    engine.activate_ability(player, apprentice, 0, targets=[target])
    assert apprentice.zone == Zone.GRAVEYARD
    engine.resolve_until_stable()
    assert target in opponent.exile and engine.state.pending_choice["player_id"] == "p1"


def test_countering_a_spell_copy_exiles_it_without_a_cast_offer():
    engine, source, player, opponent, target, answer = _board()
    # Replace the already-announced counter's target with the real stack copy.
    original = engine.rules._stack_item_for(target)
    copied, = engine.rules.copy_spell(original, "p2")
    counter = engine.rules._stack_item_for(answer)
    engine.state.stack.remove(counter)
    counter.targets = [copied.obj]
    counter.target_groups = [[copied.obj]]
    counter.target_incarnations = [copied.obj.zone_incarnation]
    engine.state.stack.append(counter)
    _resolve_counter(engine)
    assert target.zone == Zone.STACK and not engine.state.pending_choice
    assert not any(e.type == EventType.SPELL_COUNTERED for e in engine.state.events_this_turn())


def test_immediate_play_permission_and_pending_resolution_survive_clone():
    engine, source, player, opponent, target, answer = _board()
    _resolve_counter(engine)
    clone = GameEngine(engine.state.clone())
    cloned_target = clone.state.find_object(target.instance_id)
    clone.play_resolution_card(clone.state.player_by_id("p1"), cloned_target)
    clone.resolve_until_stable()
    assert cloned_target.zone == Zone.BATTLEFIELD and cloned_target.controller_id == "p1"
    assert target in opponent.exile and engine.state.pending_choice


@pytest.mark.parametrize("zone", [Zone.BATTLEFIELD, Zone.HAND, Zone.LIBRARY, Zone.EXILE])
def test_graveyard_from_anywhere_trigger_shuffles_guile_into_owners_library(zone):
    engine = game()
    source = card(engine, "Guile", zone=zone)
    owner = engine.state.player_by_id("p1")
    if zone == Zone.HAND:
        engine.rules.discard_specific(source)
    elif zone == Zone.LIBRARY:
        engine.rules.mill(owner, 1)
    else:
        engine.rules.put_into_graveyard(source)
    engine.resolve_until_stable()
    assert source in owner.library and source.zone == Zone.LIBRARY and source not in owner.graveyard


@pytest.mark.parametrize("number", [1, 2, 3])
def test_guile_requires_three_or_more_blockers(number):
    engine = game()
    player, opponent = engine.state.player_by_id("p1"), engine.state.player_by_id("p2")
    source = card(engine, "Guile")
    blockers = [filler(engine, f"Blocker {i}", player="p2", power=1, toughness=1) for i in range(number)]
    advance_to(engine, "declare_attackers")
    engine.declare_attackers(player, [{"attacker": source, "defender": opponent}])
    advance_to(engine, "declare_blockers")
    if number < 3:
        with pytest.raises(ValueError):
            engine.declare_blockers(opponent, [(obj, source) for obj in blockers])
    else:
        engine.declare_blockers(opponent, [(obj, source) for obj in blockers])
        assert len(source.blocked_by) == 3


@pytest.mark.parametrize("destination", ["exile", "hand"])
def test_graveyard_trigger_does_not_follow_guile_after_it_leaves_graveyard(destination):
    engine = game()
    source = card(engine, "Guile", zone=Zone.HAND)
    engine.rules.discard_specific(source)
    engine.rules.check_state_based_actions()
    engine.rules.put_triggers_on_stack()
    assert source.zone == Zone.GRAVEYARD and engine.state.stack
    if destination == "exile":
        engine.rules.exile(source)
    else:
        engine.rules.return_to_hand(source)
    engine.resolve_until_stable()
    assert source.zone == (Zone.EXILE if destination == "exile" else Zone.HAND)


@pytest.mark.parametrize("play", [False, True])
def test_replacement_finishes_before_counterspells_later_draw_instruction(play):
    engine, source, player, opponent, target, answer = _board(counter="Dismiss")
    _resolve_counter(engine)
    assert not player.hand and answer.zone == Zone.STACK
    if play:
        engine.play_resolution_card(player, target)
        assert target.zone == Zone.STACK
    else:
        engine.resolve_pending_choice("decline")
        assert target.zone == Zone.EXILE
    assert len(player.hand) == 1 and answer in player.graveyard


def test_activated_counter_retains_its_controller_after_source_changes_control():
    engine = game()
    player = engine.state.player_by_id("p1")
    card(engine, "Guile")
    counter_source = filler(engine, "Counter source", power=1, toughness=1, oracle_text="{T}: Counter target spell.")
    target = card(engine, "Grizzly Bears", "p2", Zone.HAND)
    engine.state.active_player_index = 1
    _announce(engine, target)
    engine.activate_ability(player, counter_source, 0, targets=[target])
    counter_source.controller_id = "p2"
    engine.resolve_until_stable()
    assert target.zone == Zone.EXILE and engine.state.pending_choice["player_id"] == "p1"


def test_multiple_guile_replacement_order_and_clone_use_affected_spells_controller():
    engine, source, player, opponent, target, answer = _board()
    card(engine, "Guile")
    _resolve_counter(engine)
    assert target.zone == Zone.STACK and engine.state.pending_choice["kind"] == "replacement_order"
    assert engine.state.pending_choice["player_id"] == "p2"
    clone = GameEngine(engine.state.clone())
    for current in (engine, clone):
        current.resolve_pending_choice("0")
        assert current.state.pending_choice["kind"] == "play_during_resolution"
        assert current.state.pending_choice["player_id"] == "p1"
        current.resolve_pending_choice("decline")
        assert current.state.find_object(target.instance_id).zone == Zone.EXILE
        assert not any(e.type == EventType.SPELL_COUNTERED for e in current.state.events_this_turn())


@pytest.mark.parametrize("clone_after_first_exile", [False, True])
def test_countering_two_spells_offers_each_exiled_card_in_order(clone_after_first_exile):
    engine = game()
    card(engine, "Guile")
    player = engine.state.player_by_id("p1")
    engine.state.active_player_index = 1
    targets = [card(engine, name, "p2", Zone.HAND) for name in ("Opt", "Consider")]
    for target in targets:
        _announce(engine, target)
    answer = filler(engine, "Two-spell counter", type_line="Instant", zone=Zone.HAND,
                    oracle_text="Counter up to two target spells.", mv=1)
    _announce(engine, answer, targets=targets)
    _resolve_counter(engine)
    assert targets[0].zone == Zone.EXILE and targets[1].zone == Zone.STACK
    if clone_after_first_exile:
        engine = GameEngine(engine.state.clone())
        targets = [engine.state.find_object(obj.instance_id) for obj in targets]
        answer = engine.state.find_object(answer.instance_id)
    engine.resolve_pending_choice("decline")
    assert targets[1].zone == Zone.EXILE and engine.state.pending_choice["kind"] == "play_during_resolution"
    engine.resolve_pending_choice("decline")
    assert answer.zone == Zone.GRAVEYARD and not engine.state.stack


@pytest.mark.parametrize("own_turn,land_used", [(True, False), (False, False), (True, True)])
def test_play_permission_can_use_a_land_back_face_but_respects_turn_and_land_limit(own_turn, land_used):
    engine = game()
    player = engine.state.player_by_id("p1")
    card(engine, "Guile")
    engine.state.active_player_index = 0 if own_turn else 1
    target = filler(engine, "Test instant front", type_line="Instant", player="p2", mv=1, zone=Zone.HAND,
        layout="modal_dfc", back_name="Test land back", back_type_line="Land", back_oracle_text="")
    _announce(engine, target)
    answer = card(engine, "Counterspell", zone=Zone.HAND)
    _announce(engine, answer, targets=[target])
    _resolve_counter(engine)
    if land_used:
        # Guile's own pending play prevents an unrelated land action; set
        # the turn's already-used allowance as the initial test condition.
        player.lands_played_this_turn = 1
    if own_turn and not land_used:
        engine.play_resolution_card(player, target, face="back")
        assert target.zone == Zone.BATTLEFIELD and target.is_land and target.controller_id == "p1"
    else:
        with pytest.raises(ValueError):
            engine.play_resolution_card(player, target, face="back")
        assert target.zone == Zone.EXILE and engine.state.pending_choice["kind"] == "play_during_resolution"
        engine.resolve_pending_choice("decline")


def test_countering_an_activated_ability_is_not_a_guile_counter_replacement():
    engine = game()
    card(engine, "Guile")
    opponent = engine.state.player_by_id("p2")
    source = filler(engine, "Opposing ability source", player="p2", power=1, toughness=1,
                    oracle_text="{T}: Draw a card.")
    engine.activate_ability(opponent, source, 0)
    ability = engine.state.stack[-1]
    answer = card(engine, "Stifle", zone=Zone.HAND)
    _announce(engine, answer, targets=[ability])
    engine.resolve_until_stable()
    assert not opponent.hand and not engine.state.pending_choice and not engine.state.stack


def test_a_modal_back_face_spell_is_a_new_front_face_card_in_exile_before_replay():
    engine = game()
    player, opponent = engine.state.player_by_id("p1"), engine.state.player_by_id("p2")
    card(engine, "Guile")
    target = filler(engine, "Test creature front", power=1, toughness=1, player="p2", mv=1, zone=Zone.HAND,
        layout="modal_dfc", back_name="Test instant back", back_type_line="Instant",
        back_mana_cost_string="{8}", back_oracle_text="")
    opponent.mana_pool.add("C", 8)
    main_phase(engine)
    engine.cast_spell(opponent, target, face="back")
    assert target.name == "Test instant back"
    answer = card(engine, "Counterspell", zone=Zone.HAND)
    _announce(engine, answer, targets=[target])
    _resolve_counter(engine)
    assert target.zone == Zone.EXILE and target.name == "Test creature front" and target.mana_value == 1
    engine.play_resolution_card(player, target)
    engine.resolve_until_stable()
    assert target.zone == Zone.BATTLEFIELD and target.name == "Test creature front" and target.controller_id == "p1"


def test_replaying_the_exiled_instant_can_choose_new_targets():
    engine = game()
    player, opponent = engine.state.player_by_id("p1"), engine.state.player_by_id("p2")
    source = card(engine, "Guile")
    spell = card(engine, "Lightning Bolt", "p2", Zone.HAND)
    _announce(engine, spell, targets=[source])
    answer = card(engine, "Counterspell", zone=Zone.HAND)
    _announce(engine, answer, targets=[spell])
    _resolve_counter(engine)
    engine.play_resolution_card(player, spell, targets=[opponent])
    engine.resolve_until_stable()
    assert opponent.life == 17 and source.damage_marked == 0
    assert spell in opponent.graveyard and answer in player.graveyard


def test_old_shuffle_trigger_does_not_move_a_later_graveyard_visit_after_new_trigger_is_countered():
    engine = game()
    source = card(engine, "Guile", zone=Zone.HAND)
    owner = engine.state.player_by_id("p1")
    engine.rules.discard_specific(source)
    engine.rules.check_state_based_actions()
    engine.rules.put_triggers_on_stack()
    original = engine.state.stack[-1]
    old_visit = source.zone_incarnation
    engine.rules.return_to_hand(source)
    engine.rules.check_state_based_actions()
    engine.rules.discard_specific(source)
    engine.rules.check_state_based_actions()
    engine.rules.put_triggers_on_stack()
    newer = engine.state.stack[-1]
    assert newer is not original and source.zone_incarnation != old_visit
    stifle = card(engine, "Stifle", zone=Zone.HAND)
    _announce(engine, stifle, targets=[newer])
    engine.resolve_until_stable()
    assert source in owner.graveyard and source not in owner.library

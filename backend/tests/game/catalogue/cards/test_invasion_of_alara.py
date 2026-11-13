"""Alara's two-hit exile and all five Maelstrom instructions in printed order."""
import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, filler, game, main_phase


NAME = "Invasion of Alara"


def _front(top):
    engine = game(library=0)
    player = engine.state.player_by_id("p1")
    objects = [card(engine, name, zone=Zone.LIBRARY) for name in reversed(top)]
    objects.reverse()
    source = card(engine, NAME, zone=Zone.HAND)
    cast(engine, source)
    return engine, source, player, objects


def _decline(engine):
    assert engine.state.pending_choice["kind"] == "play_during_resolution"
    engine.resolve_pending_choice("decline")


def test_front_enters_seven_defense_and_exiles_until_two_cheap_nonland_hits():
    engine, source, player, objects = _front(["Forest", "Grizzly Bears", "Mountain", "Ornithopter", "Island"])
    assert source.defense == 7 and source.protector_id == "p2"
    assert all(obj.zone == Zone.EXILE for obj in objects[:4])
    assert objects[4] in player.library
    assert set(engine.state.resolution_play_choice["instance_ids"]) == {objects[1].instance_id, objects[3].instance_id}
    first, second = specs_for(source.card), specs_for(source.card)
    assert first is not second and first[0] is not second[0]
    first[0].validate()


def test_declining_free_cast_takes_one_hit_and_leaves_other_hit_exiled():
    engine, source, player, objects = _front(["Forest", "Grizzly Bears", "Mountain", "Ornithopter", "Island"])
    _decline(engine)
    assert engine.state.pending_choice["kind"] == "alara_take_hand"
    engine.resolve_pending_choice(str(objects[1].instance_id))
    assert objects[1] in player.hand and objects[3] in player.exile
    assert set(player.library[:2]) == {objects[0], objects[2]}
    assert player.library[-1] is objects[4]
    assert not engine.state.free_cast_instance_ids and not engine.state.pending_choice


def test_casting_hit_is_free_then_other_hit_moves_to_hand_before_spell_resolves():
    engine, source, player, objects = _front(["Forest", "Grizzly Bears", "Ornithopter"])
    player.mana_pool.empty()
    engine.play_resolution_card(player, objects[1])
    # The original triggered ability finishes while its cast spell waits.
    assert objects[1].zone == Zone.STACK
    engine.rules.resume_deferred_effects()
    assert objects[2] in player.hand
    assert objects[0] in player.library
    assert player.mana_pool.total() == 0
    engine.resolve_until_stable()
    assert objects[1].zone == Zone.BATTLEFIELD and objects[1].mana_spent_to_cast == 0


@pytest.mark.parametrize("cast_hit", [False, True])
def test_single_hit_may_be_cast_otherwise_must_go_to_hand(cast_hit):
    engine, source, player, objects = _front(["Forest", "Ornithopter", "Mountain"])
    if cast_hit:
        engine.play_resolution_card(player, objects[1])
        engine.resolve_until_stable()
        assert objects[1].zone == Zone.BATTLEFIELD
    else:
        _decline(engine)
        assert objects[1] in player.hand
    assert set(player.library) == {objects[0], objects[2]}
    assert not player.exile


@pytest.mark.parametrize("top", [[], ["Forest", "Mountain"], ["Darksteel Colossus", "Island"]])
def test_no_hit_returns_all_exiled_misses_without_cast_offer(top):
    engine, source, player, objects = _front(top)
    assert set(player.library) == set(objects) and not player.exile
    assert not engine.state.pending_choice


def test_expensive_nonland_is_a_miss_and_cannot_be_selected_for_hand():
    engine, source, player, objects = _front(["Darksteel Colossus", "Ornithopter", "Grizzly Bears"])
    _decline(engine)
    with pytest.raises(ValueError):
        engine.resolve_pending_choice(str(objects[0].instance_id))
    engine.resolve_pending_choice(str(objects[1].instance_id))
    assert objects[0] in player.library and objects[2] in player.exile


def test_exiled_visit_pool_and_cast_decline_survive_clone():
    engine, source, player, objects = _front(["Forest", "Ornithopter", "Grizzly Bears"])
    clone = GameEngine(engine.state.clone())
    _decline(clone)
    clone.resolve_pending_choice(str(objects[1].instance_id))
    assert clone.state.find_object(objects[1].instance_id) in clone.state.player_by_id("p1").hand
    assert objects[1] in player.exile and engine.state.pending_choice["kind"] == "play_during_resolution"


def _back(players=2):
    engine = game(players=players, library=30)
    player, opponent = engine.state.player_by_id("p1"), engine.state.player_by_id("p2")
    own = filler(engine, "Own creature", power=2, toughness=2)
    enemy = filler(engine, "Enemy permanent", type_line="Artifact", player="p2")
    source = card(engine, NAME)
    source.protector_id = "p2"
    engine.rules.deal_damage(source, source.defense)
    engine.resolve_until_stable()
    assert source.zone == Zone.EXILE and source.name == "Awaken the Maelstrom"
    return engine, source, player, opponent, own, enemy


def _cast_back(engine, source, player, target_player, enemy):
    main_phase(engine)
    engine.cast_spell(player, source, target_groups=[[target_player], [enemy]])
    engine.resolve_until_stable()


def _allocate(engine, *objects):
    for obj in objects:
        assert engine.state.pending_choice["kind"] == "maelstrom_counters"
        engine.resolve_pending_choice(str(obj.instance_id))


def test_back_has_two_targets_and_color_cda_in_every_zone():
    engine, source, player, opponent, own, enemy = _back()
    assert source.colors == set("WUBRG")
    first, second = specs_for(source.card), specs_for(source.card)
    assert first is not second and first[0] is not second[0]
    first[0].validate()
    _cast_back(engine, source, player, player, enemy)
    assert source.colors == set("WUBRG") and source.zone == Zone.STACK
    assert len(player.hand) == 2
    assert engine.state.pending_choice["kind"] == "maelstrom_copy"
    engine.resolve_pending_choice(str(own.instance_id))
    token, = [o for o in engine.state.battlefield if o.is_token]
    _allocate(engine, own, token, token)
    assert own.counters.get("+1/+1", 0) == 1 and token.counters.get("+1/+1", 0) == 2
    assert enemy.zone == Zone.GRAVEYARD and source.zone == Zone.GRAVEYARD


def test_back_can_put_newly_drawn_artifact_into_play_copy_it_and_counter_the_copy():
    engine, source, player, opponent, own, enemy = _back()
    artifact = card(engine, "Ornithopter", zone=Zone.LIBRARY)
    _cast_back(engine, source, player, player, enemy)
    assert artifact in player.hand and engine.state.pending_choice["kind"] == "choose_objects"
    engine.resolve_pending_choice(str(artifact.instance_id))
    assert artifact.zone == Zone.BATTLEFIELD and engine.state.pending_choice["kind"] == "maelstrom_copy"
    engine.resolve_pending_choice(str(artifact.instance_id))
    token, = [o for o in engine.state.battlefield if o.is_token]
    _allocate(engine, token, token, token)
    assert token.name == "Ornithopter" and token.counters["+1/+1"] == 3
    assert artifact.counters.get("+1/+1", 0) == 0 and enemy.zone == Zone.GRAVEYARD


def test_artifact_put_is_optional_and_copy_cannot_choose_an_opponents_permanent():
    engine, source, player, opponent, own, enemy = _back()
    artifact = card(engine, "Ornithopter", zone=Zone.HAND)
    _cast_back(engine, source, player, opponent, enemy)
    assert len(opponent.hand) == 2 and artifact in player.hand
    engine.resolve_pending_choice("decline")
    with pytest.raises(ValueError):
        engine.resolve_pending_choice(str(enemy.instance_id))
    engine.resolve_pending_choice(str(own.instance_id))
    _allocate(engine, own, own, own)
    assert artifact.zone == Zone.HAND and own.counters["+1/+1"] == 3


def test_counter_distribution_is_chosen_in_full_before_any_counters_are_placed():
    engine, source, player, opponent, own, enemy = _back()
    _cast_back(engine, source, player, player, enemy)
    engine.resolve_pending_choice(str(own.instance_id))
    token, = [o for o in engine.state.battlefield if o.is_token]
    _allocate(engine, own, token)
    assert not own.counters and not token.counters and enemy.zone == Zone.BATTLEFIELD
    _allocate(engine, own)
    assert own.counters["+1/+1"] == 2 and token.counters["+1/+1"] == 1


def test_back_without_own_permanents_still_draws_and_destroys():
    engine, source, player, opponent, own, enemy = _back()
    engine.rules.exile(own)
    _cast_back(engine, source, player, player, enemy)
    assert len(player.hand) == 2 and enemy.zone == Zone.GRAVEYARD and source.zone == Zone.GRAVEYARD
    assert not engine.state.pending_choice


def test_counter_allocation_survives_clone_and_keeps_destroy_target():
    engine, source, player, opponent, own, enemy = _back()
    _cast_back(engine, source, player, player, enemy)
    engine.resolve_pending_choice(str(own.instance_id))
    _allocate(engine, own)
    clone = GameEngine(engine.state.clone())
    clone_own = clone.state.find_object(own.instance_id)
    _allocate(clone, clone_own, clone_own)
    assert clone_own.counters["+1/+1"] == 3
    assert clone.state.find_object(enemy.instance_id).zone == Zone.GRAVEYARD
    assert not own.counters and enemy.zone == Zone.BATTLEFIELD


def test_battle_cannot_transform_on_battlefield_into_its_sorcery_face():
    engine = game()
    source = card(engine, NAME)
    assert not engine.rules.transform_permanent(source)
    assert source.is_battle and source.zone == Zone.BATTLEFIELD


def test_sorcery_back_keeps_front_mana_value_and_requires_both_announced_targets():
    engine, source, player, opponent, own, enemy = _back()
    assert source.mana_value == 5
    main_phase(engine)
    from mtg_analyzer.game.targeting import spell_target_specs, legal_targets
    requirements = spell_target_specs(source)
    assert [spec.kind for spec in requirements] == ["player", "permanent_you_dont_control"]
    options = legal_targets(engine.state, player.id, requirements[1], source=source)
    assert enemy.instance_id in {o["instance_id"] for o in options}
    assert own.instance_id not in {o["instance_id"] for o in options}
    assert source.zone == Zone.EXILE
    engine.cast_spell(player, source, target_groups=[[player], [enemy]])
    assert source.mana_value == 5 and source.zone == Zone.STACK


def test_one_illegal_destroy_target_does_not_stop_other_instructions():
    engine, source, player, opponent, own, enemy = _back()
    main_phase(engine)
    engine.cast_spell(player, source, target_groups=[[player], [enemy]])
    engine.rules.exile(enemy)
    engine.resolve_until_stable()
    assert len(player.hand) == 2
    engine.resolve_pending_choice(str(own.instance_id))
    _allocate(engine, own, own, own)
    assert own.counters["+1/+1"] == 3 and enemy.zone == Zone.EXILE


def test_all_illegal_targets_stop_the_entire_sorcery():
    engine, source, player, opponent, own, enemy = _back(players=3)
    main_phase(engine)
    engine.cast_spell(player, source, target_groups=[[opponent], [enemy]])
    opponent.has_lost = True
    engine.rules.exile(enemy)
    engine.resolve_until_stable()
    assert not player.hand and not opponent.hand and not engine.state.pending_choice
    assert not any(o.is_token for o in engine.state.battlefield)
    assert source.zone == Zone.GRAVEYARD


def test_counters_can_be_divided_across_three_creatures_and_cannot_go_to_opponents():
    engine, source, player, opponent, own, enemy = _back()
    second = filler(engine, "Second ally", power=1, toughness=1)
    foreign = filler(engine, "Foreign creature", player="p2", power=1, toughness=1)
    _cast_back(engine, source, player, player, enemy)
    engine.resolve_pending_choice(str(own.instance_id))
    token, = [o for o in engine.state.battlefield if o.is_token]
    with pytest.raises(ValueError):
        engine.resolve_pending_choice(str(foreign.instance_id))
    _allocate(engine, own, second, token)
    assert all(o.counters.get("+1/+1", 0) == 1 for o in (own, second, token))
    assert not foreign.counters


def test_copying_a_land_with_no_creatures_skips_counter_distribution():
    engine, source, player, opponent, own, enemy = _back()
    engine.rules.exile(own)
    land = card(engine, "Forest")
    _cast_back(engine, source, player, player, enemy)
    engine.resolve_pending_choice(str(land.instance_id))
    token, = [o for o in engine.state.battlefield if o.is_token]
    assert token.is_land and not token.is_creature
    assert not engine.state.pending_choice and enemy.zone == Zone.GRAVEYARD


def test_miss_bottom_order_is_reproducible_from_cloned_search_choice():
    engine, source, player, objects = _front(["Forest", "Mountain", "Island", "Ornithopter", "Plains", "Grizzly Bears"])
    _decline(engine)
    clone = GameEngine(engine.state.clone())
    for candidate in (engine, clone):
        candidate.resolve_pending_choice(str(objects[3].instance_id))
    assert [o.instance_id for o in player.library] == [o.instance_id for o in clone.state.player_by_id("p1").library]
    assert engine.state.rng_counter == clone.state.rng_counter


@pytest.mark.parametrize("clone_during_replacement", [False, True])
def test_counter_replacement_choices_resume_each_recipient_before_destruction(clone_during_replacement):
    from mtg_analyzer.game.effects.replacements import ReplacementRegistry
    engine, source, player, opponent, own, enemy = _back()
    # Two competing replacement effects exercise the interactive placement
    # continuation without relying on any other card's Oracle implementation.
    for _ in range(2):
        effect = ReplacementRegistry.create("double_counters", {"kind": "+1/+1"})
        effect.source = own
        own.replacement_effects.append(effect)
    _cast_back(engine, source, player, player, enemy)
    engine.resolve_pending_choice(str(own.instance_id))
    token, = [o for o in engine.state.battlefield if o.is_token]
    _allocate(engine, own, token, token)
    assert engine.state.pending_choice["kind"] == "replacement_order"
    assert enemy.zone == Zone.BATTLEFIELD
    if clone_during_replacement:
        engine = GameEngine(engine.state.clone())
        own, token, enemy = [engine.state.find_object(o.instance_id) for o in (own, token, enemy)]
    choices = 0
    while engine.state.pending_choice:
        pending = engine.state.pending_choice
        assert pending["kind"] == "replacement_order"
        engine.resolve_pending_choice(pending["options"][0]["id"])
        choices += 1
    assert choices == 2
    assert own.counters["+1/+1"] == 4 and token.counters["+1/+1"] == 8
    assert enemy.zone == Zone.GRAVEYARD and not engine.state._batch_hold


def test_qualifying_card_can_be_cast_as_a_more_expensive_modal_back_face():
    engine = game(library=0)
    player = engine.state.player_by_id("p1")
    other = card(engine, "Ornithopter", zone=Zone.LIBRARY)
    modal = filler(engine, "Cheap test front", power=2, toughness=2, mv=2, zone=Zone.LIBRARY,
        layout="modal_dfc", back_name="Expensive test back", back_type_line="Sorcery",
        back_mana_cost_string="{8}", back_oracle_text="")
    source = card(engine, NAME, zone=Zone.HAND)
    cast(engine, source)
    player.mana_pool.empty()
    assert modal.instance_id in engine.state.resolution_play_choice["instance_ids"]
    engine.play_resolution_card(player, modal, face="back")
    assert modal.zone == Zone.STACK and modal.name == "Expensive test back" and modal.mana_value == 8
    assert modal.mana_spent_to_cast == 0 and other in player.hand
    engine.resolve_until_stable()
    assert modal.zone == Zone.GRAVEYARD

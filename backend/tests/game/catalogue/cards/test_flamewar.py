"""Flamewar's costs, counter-marked exile pool, and face-down privacy."""
import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.services.game_session import GameSession
from tests.support.deck_batch import activate, card, cast, filler, game, main_phase


NAME = "Flamewar, Brash Veteran"


def _board(converted=False):
    engine = game()
    source = card(engine, NAME)
    if converted:
        engine.rules.transform_permanent(source)
        engine.recompute_continuous_effects()
    return engine, source, engine.state.player_by_id("p1"), engine.state.player_by_id("p2")


def _intel(engine, name="Opt", player="p1", face_down=True):
    obj = card(engine, name, player=player, zone=Zone.HAND)
    engine.rules.exile(obj, face_down=face_down)
    engine.rules.add_counters(obj, 1, "intel")
    return obj


def test_upgrade_sacrifices_another_artifact_then_counters_and_converts():
    engine, source, player, opponent = _board()
    main_phase(engine)
    assert not engine.can_activate(player, source, source.activated_abilities[0])
    fodder = filler(engine, "Artifact", type_line="Artifact")
    engine.activate_ability(player, source, 0)
    assert fodder.zone == Zone.GRAVEYARD and not source.transformed
    engine.resolve_until_stable()
    assert source.transformed and source.counters["+1/+1"] == 1
    assert combat.has(source, "menace") and combat.has(source, "deathtouch")


def test_upgrade_only_at_sorcery_speed():
    engine, source, player, opponent = _board()
    filler(engine, "Artifact", type_line="Artifact")
    engine.state.current_phase = "combat"
    engine.state.current_step = "begin_combat"
    assert not engine.can_activate(player, source, source.activated_abilities[0])


def test_recovery_discards_hand_as_cost_then_returns_only_owned_intel_cards():
    engine, source, player, opponent = _board()
    owned = _intel(engine)
    faceup = _intel(engine, "Forest", face_down=False)
    foreign = _intel(engine, "Island", player="p2")
    unrelated = card(engine, "Mountain", zone=Zone.EXILE)
    discard = card(engine, "Grizzly Bears", zone=Zone.HAND)
    main_phase(engine)
    player.mana_pool.add("C", 1)
    engine.activate_ability(player, source, 1)
    assert not player.hand and discard.zone == Zone.GRAVEYARD and owned.zone == Zone.EXILE
    engine.resolve_until_stable()
    assert set(o.instance_id for o in player.hand) == {owned.instance_id, faceup.instance_id}
    assert foreign.zone == unrelated.zone == Zone.EXILE
    assert not owned.counters and not owned.face_down_in_exile and not owned.face_down_exile_viewers_explicit


def test_recovery_is_legal_with_an_empty_hand_and_without_intel_cards():
    engine, source, player, opponent = _board()
    player.mana_pool.add("C", 1)
    activate(engine, source, index=1)
    assert not player.hand and player.mana_pool.total() == 0


def test_combat_damage_exiles_top_cards_face_down_with_counters_then_converts():
    engine, source, player, opponent = _board(converted=True)
    earlier = card(engine, "Opt", zone=Zone.LIBRARY)
    top = card(engine, "Lightning Bolt", zone=Zone.LIBRARY)
    engine.rules.deal_damage(opponent, 2, source=source, combat=True)
    engine.resolve_until_stable()
    assert not source.transformed
    assert top in player.exile and earlier in player.exile
    assert all(o.face_down_in_exile and o.counters == {"intel": 1} for o in [earlier, top])
    assert not top.face_down_exile_viewers and not earlier.face_down_exile_viewers
    assert not engine.state.temp_play_permissions


@pytest.mark.parametrize("perspective", ["p1", "p2"])
def test_intel_identity_is_hidden_even_from_its_owner(perspective):
    engine, source, player, opponent = _board(converted=True)
    hidden = card(engine, "Lightning Bolt", zone=Zone.LIBRARY)
    engine.rules.deal_damage(opponent, 1, source=source, combat=True)
    engine.resolve_until_stable()
    view = GameSession(engine, mode="replay", starting_hand=0).view(perspective)
    exiled = next(obj for p in view["state"]["players"] for obj in p["exile"]
                  if obj["instance_id"] == hidden.instance_id)
    assert exiled["name"] != "Lightning Bolt" and exiled["counters"] == {"intel": 1}
    import json
    assert "Lightning Bolt" not in json.dumps(view)


def test_cast_converted_uses_more_than_meets_the_eye():
    engine = game()
    source = card(engine, NAME, zone=Zone.HAND)
    cast(engine, source, face="converted", pool={"B": 1, "R": 1})
    assert source.transformed and source.is_creature and len(source.triggered_abilities) == 1


def test_clone_preserves_intel_privacy_and_recovers_cards():
    engine, source, player, opponent = _board()
    hidden = _intel(engine)
    main_phase(engine)
    player.mana_pool.add("C", 1)
    engine.activate_ability(player, source, 1)
    clone = GameEngine(engine.state.clone())
    clone.resolve_until_stable()
    moved = clone.state.find_object(hidden.instance_id)
    assert moved.zone == Zone.HAND and not moved.counters
    assert hidden.zone == Zone.EXILE and hidden.face_down_exile_viewers_explicit


@pytest.mark.parametrize("size", [0, 1, 2])
def test_short_library_exiles_only_available_cards_and_still_converts(size):
    engine = game(library=size)
    source = card(engine, NAME)
    engine.rules.transform_permanent(source)
    player, opponent = engine.state.player_by_id("p1"), engine.state.player_by_id("p2")
    engine.rules.deal_damage(opponent, 3, source=source, combat=True)
    engine.resolve_until_stable()
    assert len(player.exile) == size and not player.library and not source.transformed
    assert not player.has_lost and all(o.counters == {"intel": 1} for o in player.exile)


@pytest.mark.parametrize("combat_damage,player_target", [(False, True), (True, False)])
def test_only_combat_damage_to_a_player_creates_intel(combat_damage, player_target):
    engine, source, player, opponent = _board(converted=True)
    victim = opponent if player_target else filler(engine, "Victim", player="p2", power=2, toughness=5)
    engine.rules.deal_damage(victim, 1, source=source, combat=combat_damage)
    engine.resolve_until_stable()
    assert source.transformed and not player.exile and len(player.library) == 10


def test_combat_trigger_keeps_original_controller_after_source_changes_control():
    engine, source, player, opponent = _board(converted=True)
    top = card(engine, "Opt", zone=Zone.LIBRARY)
    engine.rules.deal_damage(opponent, 1, source=source, combat=True)
    engine.rules.put_triggers_on_stack()
    source.controller_id = "p2"
    engine.resolve_until_stable()
    assert top in player.exile and not opponent.exile
    assert not source.transformed


def test_departed_combat_source_still_exiles_but_does_not_convert_new_visit():
    engine, source, player, opponent = _board(converted=True)
    top = card(engine, "Opt", zone=Zone.LIBRARY)
    engine.rules.deal_damage(opponent, 1, source=source, combat=True)
    engine.rules.put_triggers_on_stack()
    engine.rules.put_into_graveyard(source)
    engine.rules.return_from_graveyard(source, "battlefield")
    engine.resolve_until_stable()
    assert top in player.exile and not source.transformed


def test_upgrade_does_not_put_counter_on_a_reentered_source():
    engine, source, player, opponent = _board()
    filler(engine, "Artifact", type_line="Artifact")
    main_phase(engine)
    engine.activate_ability(player, source, 0)
    engine.rules.put_into_graveyard(source)
    engine.rules.return_from_graveyard(source, "battlefield")
    engine.resolve_until_stable()
    assert not source.counters and not source.transformed


def test_recovery_resolves_after_source_leaves_and_restores_owner_control():
    engine, source, player, opponent = _board()
    hidden = _intel(engine)
    hidden.controller_id = "p2"
    main_phase(engine)
    player.mana_pool.add("C", 1)
    engine.activate_ability(player, source, 1)
    engine.rules.put_into_graveyard(source)
    engine.resolve_until_stable()
    assert hidden in player.hand and hidden.controller_id == "p1"


def test_specs_are_fresh_for_both_faces():
    from mtg_analyzer.game.card_registry import specs_for
    engine, source, player, opponent = _board()
    for _ in range(2):
        first, second = specs_for(source.card), specs_for(source.card)
        assert first[0] is not second[0]
        index = 0 if not source.transformed else 3
        assert first[index].effects[0] is not second[index].effects[0]
        engine.rules.transform_permanent(source)

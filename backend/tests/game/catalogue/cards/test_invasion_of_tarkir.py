"""Invasion of Tarkir's revealed Dragon count and Defiant Thundermaw's dealers."""
import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, filler, game
from tests.support.star_trek import advance_to


NAME = "Invasion of Tarkir"


def _board(dragons=0):
    engine = game()
    player, opponent = engine.state.player_by_id("p1"), engine.state.player_by_id("p2")
    chosen = [filler(engine, f"Dragon {i}", type_line="Creature — Dragon", power=2, toughness=2,
                     zone=Zone.HAND) for i in range(dragons)]
    source = card(engine, NAME, zone=Zone.HAND)
    cast(engine, source)
    return engine, source, player, opponent, chosen


def _finish_target(engine, target="p2", resolve=True):
    pending = engine.state.pending_choice
    assert pending["kind"] == "trigger_target"
    assert target in {o["id"] for o in pending["options"]}
    engine.rules.resolve_choice(target)
    assert engine.state.stack
    if resolve:
        engine.resolve_until_stable()


def test_zero_dragons_still_creates_two_damage_reflexive_trigger():
    engine, source, player, opponent, chosen = _board()
    assert source.defense == 5 and source.protector_id == "p2"
    assert engine.state.pending_choice["kind"] == "trigger_target"
    assert str(source.instance_id) not in {o["id"] for o in engine.state.pending_choice["options"]}
    _finish_target(engine)
    assert opponent.life == 18 and source.zone == Zone.BATTLEFIELD


@pytest.mark.parametrize("number", [0, 1, 3])
def test_can_choose_any_subset_and_targets_only_after_revealing(number):
    engine, source, player, opponent, dragons = _board(3)
    assert engine.state.pending_choice["kind"] == "tarkir_reveal_dragons"
    for obj in dragons[:number]:
        engine.resolve_pending_choice(str(obj.instance_id))
    if engine.state.pending_choice["kind"] == "tarkir_reveal_dragons":
        engine.resolve_pending_choice("done")
    assert not engine.state.stack  # The reflexive target announcement is still pending.
    reveals = [e.get("instance_id") for e in engine.state.events_this_turn() if e.type == EventType.REVEAL]
    assert set(reveals) == {o.instance_id for o in dragons[:number]}
    assert all(obj in player.hand for obj in dragons)
    _finish_target(engine)
    assert opponent.life == 18 - number


def test_selection_is_not_public_until_the_full_reveal_is_chosen():
    engine, source, player, opponent, dragons = _board(2)
    engine.resolve_pending_choice(str(dragons[0].instance_id))
    assert not any(e.type == EventType.REVEAL for e in engine.state.events_this_turn())
    engine.resolve_pending_choice("done")
    assert sum(e.type == EventType.REVEAL for e in engine.state.events_this_turn()) == 1


def test_only_dragon_cards_are_offered_including_changeling():
    engine = game()
    dragon = filler(engine, "Dragon", type_line="Creature — Dragon", power=1, toughness=1, zone=Zone.HAND)
    changeling = card(engine, "Mirror Entity", zone=Zone.HAND)
    misleading = filler(engine, "Dragon named but not typed", type_line="Creature — Human", power=1, toughness=1, zone=Zone.HAND)
    source = card(engine, NAME, zone=Zone.HAND)
    cast(engine, source)
    options = engine.state.pending_choice["options"]
    assert {o["instance_id"] for o in options if "instance_id" in o} == {dragon.instance_id, changeling.instance_id}
    assert misleading.zone == Zone.HAND


def test_revealed_count_is_fixed_when_cards_later_leave_the_hand():
    engine, source, player, opponent, dragons = _board(1)
    engine.resolve_pending_choice(str(dragons[0].instance_id))
    _finish_target(engine, resolve=False)
    engine.rules.put_into_graveyard(dragons[0])
    engine.resolve_until_stable()
    assert opponent.life == 17


def test_illegal_reflexive_target_stops_damage_without_reversing_reveal():
    engine, source, player, opponent, dragons = _board(1)
    victim = filler(engine, "Victim", player="p2", power=1, toughness=5)
    engine.resolve_pending_choice(str(dragons[0].instance_id))
    _finish_target(engine, str(victim.instance_id), resolve=False)
    engine.rules.put_into_graveyard(victim)
    engine.resolve_until_stable()
    assert opponent.life == 20 and dragons[0] in player.hand
    assert not any(e.type == EventType.DAMAGE for e in engine.state.events_this_turn())


def test_reveal_choice_and_damage_count_survive_clone():
    engine, source, player, opponent, dragons = _board(2)
    engine.resolve_pending_choice(str(dragons[0].instance_id))
    clone = GameEngine(engine.state.clone())
    clone.resolve_pending_choice("done")
    _finish_target(clone)
    assert clone.state.player_by_id("p2").life == 17 and opponent.life == 20
    assert engine.state.pending_choice["kind"] == "tarkir_reveal_dragons"


def _back_board():
    engine, source, player, opponent, _ = _board()
    _finish_target(engine)
    engine.rules.deal_damage(source, source.defense)
    engine.resolve_until_stable()
    assert source.zone == Zone.EXILE
    engine.cast_spell(player, source)
    engine.resolve_until_stable()
    source.summoning_sick = False
    return engine, source, player, opponent


def test_defeated_siege_casts_the_complete_dragon_face():
    engine, source, player, opponent = _back_board()
    assert source.name == "Defiant Thundermaw" and source.is_creature and source.has_subtype("Dragon")
    assert combat.has(source, "flying") and combat.has(source, "trample")
    assert len(source.triggered_abilities) == 1 and source.mana_spent_to_cast == 0


def test_each_attacking_dragon_deals_its_own_damage():
    engine, source, player, opponent = _back_board()
    other = filler(engine, "Other Dragon", type_line="Creature — Dragon", power=2, toughness=2)
    advance_to(engine, "declare_attackers")
    engine.declare_attackers(player, [{"attacker": obj, "defender": opponent} for obj in (source, other)])
    engine.resolve_until_stable()
    while engine.state.pending_choice:
        assert engine.state.pending_choice["kind"] == "trigger_target"
        engine.resolve_pending_choice("p2")
    engine.resolve_until_stable()
    damage = [e for e in engine.state.events_this_turn() if e.type == EventType.DAMAGE and e.get("amount") == 2]
    assert {e.get("source_id") for e in damage} == {source.instance_id, other.instance_id}
    assert opponent.life == 14


def test_invalid_or_duplicate_reveal_choice_preserves_selection():
    engine, source, player, opponent, dragons = _board(2)
    wrong = filler(engine, "Not a Dragon", type_line="Creature — Human", power=1, toughness=1, zone=Zone.HAND)
    with pytest.raises(ValueError):
        engine.resolve_pending_choice(str(wrong.instance_id))
    engine.resolve_pending_choice(str(dragons[0].instance_id))
    with pytest.raises(ValueError):
        engine.resolve_pending_choice(str(dragons[0].instance_id))
    assert not any(e.type == EventType.REVEAL for e in engine.state.events_this_turn())
    engine.resolve_pending_choice("done")
    _finish_target(engine)
    assert opponent.life == 17


def test_reflexive_damage_uses_the_departed_sieges_last_known_visit():
    engine, source, player, opponent, dragons = _board()
    old_visit = source.zone_incarnation
    _finish_target(engine, resolve=False)
    engine.rules.exile(source)
    engine.resolve_until_stable()
    assert opponent.life == 18 and source.zone == Zone.EXILE
    damage = [e for e in engine.state.events_this_turn() if e.type == EventType.DAMAGE]
    assert len(damage) == 1 and damage[0].get("source_zone_incarnation") == old_visit


def test_later_visit_of_the_siege_is_a_legal_other_target():
    from tests.support.deck_batch import RICH, main_phase
    engine = game()
    player = engine.state.player_by_id("p1")
    source = card(engine, NAME, zone=Zone.HAND)
    main_phase(engine)
    player.mana_pool.add_many(RICH)
    engine.cast_spell(player, source)
    engine.rules.resolve_top_of_stack()
    engine.rules.put_triggers_on_stack()
    assert source.zone == Zone.BATTLEFIELD and engine.state.stack
    old_visit = source.zone_incarnation
    engine.rules.exile(source)
    engine.rules.return_from_graveyard(source, "battlefield")
    engine.resolve_until_stable()
    # The new visit's ETB resolves first and cannot target itself.
    assert str(source.instance_id) not in {o["id"] for o in engine.state.pending_choice["options"]}
    _finish_target(engine)
    # The original ETB can now target this different battlefield object.
    assert source.zone_incarnation != old_visit
    _finish_target(engine, str(source.instance_id))
    assert source.defense == 3
    damage = next(e for e in engine.state.events_this_turn()
                  if e.type == EventType.DAMAGE and e.get("target_id") == source.instance_id)
    assert damage.get("source_zone_incarnation") == old_visit


def test_damage_target_can_be_the_abilities_controller():
    engine, source, player, opponent, dragons = _board()
    _finish_target(engine, "p1")
    assert player.life == 18 and opponent.life == 20


def test_non_dragon_attack_does_not_trigger_thundermaw():
    engine, source, player, opponent = _back_board()
    other = filler(engine, "Human", type_line="Creature — Human", power=2, toughness=2)
    advance_to(engine, "declare_attackers")
    engine.declare_attackers(player, [{"attacker": other, "defender": opponent}])
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None and opponent.life == 18


def test_opponents_dragon_attack_does_not_trigger_thundermaw():
    engine, source, player, opponent = _back_board()
    other = filler(engine, "Their Dragon", player="p2", type_line="Creature — Dragon", power=2, toughness=2)
    engine.state.active_player_index = 1
    advance_to(engine, "declare_attackers")
    engine.declare_attackers(opponent, [{"attacker": other, "defender": player}])
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None and player.life == 20


def test_catalogue_specs_are_fresh_for_each_face():
    from mtg_analyzer.game.card_registry import specs_for
    engine, source, player, opponent, dragons = _board()
    for index in (0, 2):
        first, second = specs_for(source.card), specs_for(source.card)
        assert first[index] is not second[index] and first[index].effects[0] is not second[index].effects[0]
        engine.rules.transform_permanent(source)

"""Megatron's combat spell lock, postcombat conversion, and reflexive damage."""
import pytest

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import RICH, card, filler, game
from tests.support.star_trek import advance_to


NAME = "Megatron, Tyrant"


def _board(converted=False, players=2):
    engine = game(players=players)
    source = card(engine, NAME)
    if converted:
        engine.rules.transform_permanent(source)
        engine.recompute_continuous_effects()
    return engine, source, engine.state.player_by_id("p1"), engine.state.player_by_id("p2")


def _main2(engine):
    engine.state.current_phase = "postcombat_main"
    engine.state.current_step = "main2"
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="main2"))
    engine.resolve_until_stable()


def _attack(engine, source, player, opponent):
    advance_to(engine, "declare_attackers")
    engine.declare_attackers(player, [{"attacker": source, "defender": opponent}])
    engine.resolve_until_stable()


def _damage_board(amount=6, toughness=4):
    engine, source, player, opponent = _board(converted=True)
    artifact = filler(engine, "Artifact", type_line="Artifact", mv=amount)
    target = filler(engine, "Target", player="p2", power=1, toughness=toughness)
    return engine, source, player, opponent, artifact, target


def _sacrifice(engine, artifact, target, resolve=True):
    engine.resolve_pending_choice(str(artifact.instance_id))
    assert artifact.zone == Zone.GRAVEYARD
    assert engine.state.pending_choice["kind"] == "trigger_target"
    engine.rules.resolve_choice(str(target.instance_id))
    assert engine.state.stack
    if resolve:
        engine.resolve_until_stable()


@pytest.mark.parametrize("active", [0, 1])
def test_opponents_cannot_cast_during_either_players_combat(active):
    engine, source, player, opponent = _board()
    own = card(engine, "Opt", zone=Zone.HAND)
    theirs = card(engine, "Opt", player="p2", zone=Zone.HAND)
    for p in (player, opponent):
        p.mana_pool.add_many(RICH)
    engine.state.active_player_index = active
    engine.state.current_phase = "combat"
    engine.state.current_step = "begin_combat"
    assert engine.can_cast(player, own) and not engine.can_cast(opponent, theirs)
    engine.state.current_phase = "postcombat_main"
    engine.state.current_step = "main2"
    assert engine.can_cast(opponent, theirs)


def test_converting_removes_the_combat_spell_lock():
    engine, source, player, opponent = _board()
    spell = card(engine, "Opt", player="p2", zone=Zone.HAND)
    opponent.mana_pool.add_many(RICH)
    engine.state.current_phase = "combat"
    engine.state.current_step = "begin_combat"
    assert not engine.can_cast(opponent, spell)
    engine.rules.transform_permanent(source)
    assert engine.can_cast(opponent, spell)


def test_postcombat_mana_counts_all_opponents_gross_life_loss_at_resolution():
    engine, source, player, opponent = _board(players=3)
    third = engine.state.player_by_id("p3")
    engine.rules.lose_life(opponent, 2)
    engine.rules.gain_life(opponent, 5)
    engine.rules.lose_life(third, 3)
    engine.rules.lose_life(player, 7)
    _main2(engine)
    assert engine.state.pending_choice["kind"] == "megatron_convert_mana"
    engine.rules.lose_life(third, 1)
    engine.resolve_pending_choice("convert")
    assert source.transformed and player.mana_pool.pool.get("C") == 6


def test_postcombat_conversion_is_optional():
    engine, source, player, opponent = _board()
    engine.rules.lose_life(opponent, 3)
    _main2(engine)
    engine.resolve_pending_choice("decline")
    assert not source.transformed and player.mana_pool.total() == 0


def test_front_does_not_offer_conversion_in_precombat_or_opponents_main_phase():
    engine, source, player, opponent = _board()
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="main1"))
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None
    engine.state.active_player_index = 1
    _main2(engine)
    assert engine.state.pending_choice is None


def test_cannot_generate_mana_after_source_leaves_the_offered_choice():
    engine, source, player, opponent = _board()
    engine.rules.lose_life(opponent, 3)
    _main2(engine)
    engine.rules.exile(source)
    engine.resolve_pending_choice("convert")
    assert source.zone == Zone.EXILE and player.mana_pool.total() == 0


@pytest.mark.parametrize("amount,converted,life", [(2, False, 20), (4, False, 20), (6, True, 18)])
def test_only_excess_damage_redirects_and_converts(amount, converted, life):
    engine, source, player, opponent, artifact, target = _damage_board(amount)
    _attack(engine, source, player, opponent)
    assert {o.get("instance_id") for o in engine.state.pending_choice["options"] if o["id"] != "decline"} == {artifact.instance_id}
    _sacrifice(engine, artifact, target)
    assert source.transformed is not converted and opponent.life == life
    assert target.zone == (Zone.GRAVEYARD if amount >= 4 else Zone.BATTLEFIELD)
    damage = [e.get("amount") for e in engine.state.events_this_turn()
              if e.type == EventType.DAMAGE and e.get("target_id") == target.instance_id]
    assert damage == [min(amount, 4)]


def test_sacrifice_is_optional_and_does_not_target_a_creature_until_paid():
    engine, source, player, opponent, artifact, target = _damage_board()
    _attack(engine, source, player, opponent)
    assert engine.state.pending_choice["kind"] == "megatron_sacrifice" and not engine.state.stack
    engine.resolve_pending_choice("decline")
    assert artifact.zone == Zone.BATTLEFIELD and target.damage_marked == 0 and source.transformed


def test_marked_damage_reduces_lethal_before_redirect():
    engine, source, player, opponent, artifact, target = _damage_board(4)
    engine.rules.deal_damage(target, 2)
    _attack(engine, source, player, opponent)
    _sacrifice(engine, artifact, target)
    assert not source.transformed and opponent.life == 18


def test_deathtouch_makes_one_damage_lethal():
    engine, source, player, opponent, artifact, target = _damage_board(3)
    source.temp_keywords.add("deathtouch")
    engine.recompute_continuous_effects()
    _attack(engine, source, player, opponent)
    _sacrifice(engine, artifact, target)
    assert target.zone == Zone.GRAVEYARD and opponent.life == 18 and not source.transformed


def test_indestructibility_does_not_change_excess_calculation():
    engine, source, player, opponent, artifact, target = _damage_board()
    target.temp_keywords.add("indestructible")
    engine.recompute_continuous_effects()
    _attack(engine, source, player, opponent)
    _sacrifice(engine, artifact, target)
    assert target.zone == Zone.BATTLEFIELD and target.damage_marked == 4
    assert opponent.life == 18 and not source.transformed


def test_illegal_target_stops_damage_and_conversion_but_keeps_sacrifice():
    engine, source, player, opponent, artifact, target = _damage_board()
    _attack(engine, source, player, opponent)
    _sacrifice(engine, artifact, target, resolve=False)
    engine.rules.put_into_graveyard(target)
    engine.resolve_until_stable()
    assert source.transformed and opponent.life == 20 and artifact.zone == Zone.GRAVEYARD


def test_prevention_does_not_recompute_the_split_or_stop_conversion():
    engine, source, player, opponent, artifact, target = _damage_board()
    engine.rules.prevent_damage_to_target(target, "all")
    engine.rules.prevent_damage_to_target(opponent, "all")
    _attack(engine, source, player, opponent)
    _sacrifice(engine, artifact, target)
    assert target.zone == Zone.BATTLEFIELD and target.damage_marked == 0
    assert opponent.life == 20 and not source.transformed


@pytest.mark.parametrize("amount,life,converted", [(4, 20, False), (6, 16, True)])
def test_damage_replacements_apply_after_the_original_excess_split(amount, life, converted):
    from mtg_analyzer.game.effects.core import ReplacementEffect
    engine, source, player, opponent, artifact, target = _damage_board(amount)
    source_id = source.instance_id
    source.replacement_effects.append(ReplacementEffect(
        EventType.DAMAGE, lambda e, c: e.copy_with(amount=e.get("amount") * 2),
        condition=lambda e, c: e.get("source_id") == source_id, source=source))
    _attack(engine, source, player, opponent)
    _sacrifice(engine, artifact, target)
    assert opponent.life == life and source.transformed is not converted


def test_damage_is_simultaneous_and_conversion_happens_after_both_receipts():
    engine, source, player, opponent, artifact, target = _damage_board()
    source.temp_keywords.add("lifelink")
    engine.recompute_continuous_effects()
    faces_during_damage = []
    engine.state.subscribe(lambda event: faces_during_damage.append(source.transformed)
                           if event.type == EventType.DAMAGE else None)
    _attack(engine, source, player, opponent)
    _sacrifice(engine, artifact, target)
    assert faces_during_damage == [True, True]
    assert not source.transformed and player.life == 26
    gains = [e.get("amount") for e in engine.state.events_this_turn() if e.type == EventType.LIFE_GAINED]
    assert gains == [6]


def test_conversion_waits_for_replacement_order_and_survives_clone():
    from mtg_analyzer.game.effects.core import ReplacementEffect
    from tests.support.deck_batch import answer
    engine, source, player, opponent, artifact, target = _damage_board()
    source_id = source.instance_id
    for replace in (lambda e, c: e.copy_with(amount=e.get("amount") * 2),
                    lambda e, c: e.copy_with(amount=e.get("amount") + 1)):
        source.replacement_effects.append(ReplacementEffect(EventType.DAMAGE, replace,
            condition=lambda e, c: e.get("source_id") == source_id, source=source))
    _attack(engine, source, player, opponent)
    _sacrifice(engine, artifact, target)
    assert engine.state.pending_choice["kind"] == "replacement_order" and source.transformed
    clone = GameEngine(engine.state.clone())
    answer(engine)
    engine.resolve_until_stable()
    answer(clone)
    clone.resolve_until_stable()
    assert not source.transformed and not clone.state.find_object(source.instance_id).transformed
    assert opponent.life == clone.state.player_by_id("p2").life


def test_artifact_mana_value_is_captured_before_it_leaves_the_battlefield():
    engine, source, player, opponent, artifact, target = _damage_board()
    _attack(engine, source, player, opponent)
    _sacrifice(engine, artifact, target, resolve=False)
    artifact.card.converted_mana_cost = 0
    engine.resolve_until_stable()
    assert opponent.life == 18 and not source.transformed


def test_departed_source_uses_last_known_deathtouch_and_does_not_convert_new_visit():
    engine, source, player, opponent, artifact, target = _damage_board(3)
    source.temp_keywords.add("deathtouch")
    engine.recompute_continuous_effects()
    _attack(engine, source, player, opponent)
    _sacrifice(engine, artifact, target, resolve=False)
    engine.rules.exile(source)
    engine.rules.return_from_graveyard(source, "battlefield")
    assert not source.transformed
    engine.resolve_until_stable()
    assert target.zone == Zone.GRAVEYARD and opponent.life == 18 and not source.transformed


def test_clone_preserves_artifact_choice_and_reflexive_targeting():
    engine, source, player, opponent, artifact, target = _damage_board()
    _attack(engine, source, player, opponent)
    clone = GameEngine(engine.state.clone())
    _sacrifice(clone, clone.state.find_object(artifact.instance_id), clone.state.find_object(target.instance_id))
    assert not clone.state.find_object(source.instance_id).transformed
    assert source.transformed and artifact.zone == Zone.BATTLEFIELD


def test_more_than_meets_the_eye_and_fresh_specs_for_both_faces():
    from mtg_analyzer.game.card_registry import specs_for
    from tests.support.deck_batch import cast
    engine = game()
    source = card(engine, NAME, zone=Zone.HAND)
    cast(engine, source, face="converted", pool={"C": 1, "R": 1, "W": 1, "B": 1})
    assert source.transformed and source.is_creature and len(source.triggered_abilities) == 1
    for index in (1, 0):
        first, second = specs_for(source.card), specs_for(source.card)
        assert first[index] is not second[index] and first[index].effects[0] is not second[index].effects[0]
        engine.rules.transform_permanent(source)


def test_zero_mana_value_artifact_is_sacrificed_without_damage_or_conversion():
    engine, source, player, opponent, artifact, target = _damage_board(0)
    _attack(engine, source, player, opponent)
    _sacrifice(engine, artifact, target)
    assert source.transformed and opponent.life == 20 and target.damage_marked == 0
    assert not any(e.type == EventType.DAMAGE for e in engine.state.events_this_turn())


def test_postcombat_can_convert_even_when_no_opponent_lost_life():
    engine, source, player, opponent = _board()
    _main2(engine)
    engine.resolve_pending_choice("convert")
    assert source.transformed and player.mana_pool.total() == 0

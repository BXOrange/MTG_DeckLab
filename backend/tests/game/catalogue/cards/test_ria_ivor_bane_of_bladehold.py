"""Ria Ivor replaces one combat-damage occurrence, then creates Mites."""
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType, GameEvent
from tests.support.star_trek import advance_to, attack, game, on_battlefield, vanilla


def _board():
    engine, p1, p2 = game(via_steps=True)
    ria = on_battlefield(engine, "p1", "Ria Ivor, Bane of Bladehold")
    creature = vanilla(engine, "p1", "Attacker", 3, 4)
    advance_to(engine, "begin_combat")
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice["kind"] == "trigger_target"
    engine.resolve_pending_choice(str(creature.instance_id))
    engine.resolve_until_stable()
    return engine, p1, p2, ria, creature


def _mites(engine):
    return [obj for obj in engine.state.permanents() if obj.is_token and "Mite" in obj.card.type_line]


def test_actual_combat_prevents_players_damage_and_makes_mites_with_battle_cry():
    engine, p1, p2, ria, creature = _board()
    a, b = specs_for(ria.card), specs_for(ria.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    attack(engine, p1, ria, creature)
    # Ria deals her printed 3; her battle cry makes the other attacker 4 power.
    assert p2.life == 17
    mites = _mites(engine)
    assert len(mites) == 4
    assert all(obj.controller_id == "p1" and obj.power == obj.toughness == 1 for obj in mites)
    assert all("Artifact" in obj.card.type_line and combat.has(obj, "cant_block") for obj in mites)
    assert all(obj.parametric_keyword_value("toxic") == 1 for obj in mites)


def test_only_next_occurrence_is_prevented():
    engine, p1, p2, ria, creature = _board()
    engine.rules.deal_combat_damage([(p2, 3, creature)])
    assert p2.life == 20 and len(_mites(engine)) == 3
    engine.rules.deal_combat_damage([(p2, 3, creature)])
    assert p2.life == 17 and len(_mites(engine)) == 3


def test_double_strike_prevents_first_strike_damage_but_not_regular_damage():
    engine, p1, p2, ria, creature = _board()
    creature.temp_keywords.add("double_strike")
    attack(engine, p1, creature)
    assert p2.life == 17 and len(_mites(engine)) == 3


def test_zero_damage_does_not_consume_next_occurrence():
    engine, p1, p2, ria, creature = _board()
    engine.rules.deal_combat_damage([(p2, 0, creature)])
    assert not _mites(engine)
    engine.rules.deal_combat_damage([(p2, 3, creature)])
    assert p2.life == 20 and len(_mites(engine)) == 3


def test_noncombat_and_creature_damage_do_not_consume_shield():
    engine, p1, p2, ria, creature = _board()
    blocker = vanilla(engine, "p2", "Blocker", 2, 5)
    engine.rules.deal_damage(p2, 1, source=creature)
    engine.rules.deal_combat_damage([(blocker, 2, creature)])
    assert p2.life == 19 and blocker.damage_marked == 2 and not _mites(engine)
    engine.rules.deal_combat_damage([(p2, 3, creature)])
    assert p2.life == 19 and len(_mites(engine)) == 3


def test_simultaneous_player_recipients_make_one_batch_of_the_total_mites():
    engine, p1, p2, ria, creature = _board()
    engine.rules.deal_combat_damage([(p1, 2, creature), (p2, 3, creature)])
    assert p1.life == p2.life == 20 and len(_mites(engine)) == 5
    batches = [event for event in engine.state.events_this_turn() if event.type == EventType.EVENT_BATCH
               and event.get("batch_of") == EventType.ENTERS_BATTLEFIELD
               and len(event.get("members", [])) == 5]
    assert len(batches) == 1


def test_unpreventable_damage_creates_no_mites_and_does_not_consume_shield():
    engine, p1, p2, ria, creature = _board()
    engine.rules.disable_damage_prevention_this_turn()
    engine.rules.deal_combat_damage([(p2, 3, creature)])
    assert p2.life == 17 and not _mites(engine)
    engine.state.damage_prevention_disabled = False
    engine.rules.deal_combat_damage([(p2, 3, creature)])
    assert p2.life == 17 and len(_mites(engine)) == 3


def test_shield_expires_at_combat_end():
    engine, p1, p2, ria, creature = _board()
    advance_to(engine, "main2")
    engine.rules.deal_combat_damage([(p2, 3, creature)])
    assert p2.life == 17 and not _mites(engine)


def test_shield_survives_ria_leaving_and_creates_tokens_for_original_controller():
    engine, p1, p2, ria, creature = _board()
    engine.rules.exile(ria)
    engine.rules.deal_combat_damage([(p2, 3, creature)])
    assert p2.life == 20 and len(_mites(engine)) == 3
    assert all(obj.controller_id == "p1" for obj in _mites(engine))


def test_clone_prevention_does_not_mutate_original_shield():
    engine, p1, p2, ria, creature = _board()
    clone = GameEngine(engine.state.clone())
    clone.rules.deal_combat_damage([(clone.state.player_by_id("p2"), 3, clone.state.find_object(creature.instance_id))])
    assert len(_mites(clone)) == 3 and not _mites(engine)
    engine.rules.deal_combat_damage([(p2, 3, creature)])
    assert len(_mites(engine)) == 3


def test_does_not_trigger_on_opponents_combat():
    engine, p1, p2 = game()
    on_battlefield(engine, "p1", "Ria Ivor, Bane of Bladehold")
    engine.state.active_player_index = 1
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="begin_combat", player_id="p2"))
    engine.resolve_until_stable()
    assert not engine.state.pending_choice and not engine.state.stack

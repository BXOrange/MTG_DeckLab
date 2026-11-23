"""Exercise the new restrictions through bound cached cards and turn windows."""
import pytest

from mtg_analyzer.game import continuous, durations
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from tests.test_par290_restrictions import _bear, _can_attack, _cast_real, _engine, _named, _put, _real


@pytest.mark.parametrize("name", [
    "Avatar's Wrath", "Conjurer's Ban", "Azor, the Lawbringer", "Disorienting Glower",
    "Academic Probation", "Reflector Mage", "Giant Turtle", "Halls of Mist", "Arboria",
    "Bound in Gold", "Intercessor's Arrest", "Revoke Privileges",
])
def test_card_is_modeled(name):
    assert parse_oracle(_named(name)).modeled


def _turn(engine, index):
    if engine.state.internal_turn.number == 0 and index != 0:
        engine.begin_turn()
    if engine.state.internal_turn.number and engine.state.next_active_index() != index:
        engine.state.extra_turns.append(engine.state.players[index].id)
    engine.begin_turn()
    assert engine.state.active_player_index == index
    return engine.state.active_player


@pytest.mark.parametrize("name", ["Bound in Gold", "Intercessor's Arrest", "Revoke Privileges"])
def test_aura_removes_creature_from_actual_crew_payment_but_allows_station(name):
    engine = _engine()
    crew = _put(engine, _bear("Crew", power=5))
    vehicle = _real(engine, "Smuggler's Copter")
    aura = _real(engine, name, "p2")
    player = engine.state.active_player
    engine.state.current_step = "main1"
    assert engine._resolve_crew_cost(player, vehicle, 1, [crew.instance_id]) == [crew]

    aura.attached_to = crew.instance_id
    engine.recompute_continuous_effects()
    assert crew not in engine._crew_pool(player, vehicle)
    assert engine._resolve_crew_cost(player, vehicle, 1, [crew.instance_id]) is None
    assert engine._resolve_station_cost(player, vehicle, [crew.instance_id]) == [crew]
    assert engine._resolve_crew_cost(player, vehicle, 1, [crew.instance_id], crewing=False) == [crew]
    assert engine._resolve_crew_cost(player, vehicle, 1, [crew.instance_id], plain_power=True) == [crew]
    engine.rules.put_into_graveyard(aura)
    engine.recompute_continuous_effects()
    assert crew in engine._crew_pool(player, vehicle)


@pytest.mark.parametrize("history_card", ["Giant Turtle", "Halls of Mist"])
def test_history_checks_previous_own_turn_and_exact_zone_visit(history_card):
    engine = _engine(3)
    source = _real(engine, history_card)
    attacker = source if history_card == "Giant Turtle" else _put(engine, _bear())
    player = _turn(engine, 0)
    attacker.summoning_sick = False
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(player, [
        {"attacker": attacker, "defender": {"kind": "player", "id": "p2"}}
    ])
    _turn(engine, 1)
    _turn(engine, 2)
    _turn(engine, 0)
    attacker.tapped = attacker.summoning_sick = False
    engine = GameEngine(engine.state.clone())
    attacker = engine.state.find_object(attacker.instance_id)
    assert not _can_attack(engine, attacker, "p2")
    attacker.zone_incarnation += 1
    assert _can_attack(engine, attacker, "p2")


@pytest.mark.parametrize("activity,allowed", [
    (EventType.SPELL_CAST, True), (EventType.ENTERS_BATTLEFIELD, True),
    ("someone_elses_permanent", True), ("token", False), (None, False),
])
def test_arboria_reads_defenders_previous_turn_across_snapshots(activity, allowed):
    engine = _engine(3)
    _real(engine, "Arboria")
    attacker = _put(engine, _bear())
    _turn(engine, 1)
    if activity == "someone_elses_permanent":
        permanent = _put(engine, _bear("Returned"), "p3")
        engine.rules.put_into_graveyard(permanent)
        engine.rules.return_from_graveyard(permanent, put_by_player_id="p2")
    elif activity:
        event = EventType.ENTERS_BATTLEFIELD if activity == "token" else activity
        engine.state.fire_event(GameEvent(event, player_id="p2", controller_id="p2", is_token=activity == "token"))
    _turn(engine, 2)
    _turn(engine, 0)
    engine = GameEngine(engine.state.clone())
    attacker = engine.state.find_object(attacker.instance_id)
    assert _can_attack(engine, attacker, "p2") == allowed
    assert not _can_attack(engine, attacker, "p3")
    assert _can_attack(engine, attacker, "p2", kind="planeswalker")


def test_azors_restriction_tracks_each_opponents_next_turn_through_cleanup():
    engine = _engine(3)
    _turn(engine, 0)
    source = _cast_real(engine, "Azor, the Lawbringer")
    engine.rules.put_into_graveyard(source)
    bolt, bear = _named("Lightning Bolt"), _bear()
    p2, p3 = engine.state.players[1:]
    assert not continuous.cast_prohibited(engine.state, p2, bolt)
    _turn(engine, 1)
    assert continuous.cast_prohibited(engine.state, p2, bolt)
    assert not continuous.cast_prohibited(engine.state, p2, bear)
    assert not continuous.cast_prohibited(engine.state, p3, bolt)
    durations.sweep(engine.state, "cleanup")
    assert continuous.cast_prohibited(engine.state, p2, bolt)
    _turn(engine, 2)
    assert not continuous.cast_prohibited(engine.state, p2, bolt)
    assert continuous.cast_prohibited(engine.state, p3, bolt)
    _turn(engine, 0)
    _turn(engine, 1)
    assert not continuous.cast_prohibited(engine.state, p2, bolt)


def test_conjurers_ban_names_a_land_and_expires_at_creators_next_turn():
    engine = _engine()
    forest, plains = _named("Forest"), _named("Plains")
    _turn(engine, 0)
    _cast_real(engine, "Conjurer's Ban")
    assert engine.state.pending_choice["kind"] == "name_card"
    engine = GameEngine(engine.state.clone())
    engine.resolve_pending_choice("Forest")
    for seat in engine.state.players:
        assert continuous.land_play_prohibited(engine.state, seat, forest)
        assert not continuous.land_play_prohibited(engine.state, seat, plains)
    _turn(engine, 1)
    assert continuous.land_play_prohibited(engine.state, engine.state.active_player, forest)
    _turn(engine, 0)
    assert not continuous.land_play_prohibited(engine.state, engine.state.active_player, forest)


def test_avatar_wrath_hand_exception_survives_its_source_in_exile():
    engine = _engine()
    _turn(engine, 0)
    source = _cast_real(engine, "Avatar's Wrath")
    caster, opponent = engine.state.players
    bolt = _named("Lightning Bolt")
    assert source.zone == Zone.EXILE
    assert continuous.cast_prohibited(engine.state, opponent, bolt, Zone.EXILE)
    assert not continuous.cast_prohibited(engine.state, opponent, bolt, Zone.HAND)
    assert not continuous.cast_prohibited(engine.state, caster, bolt, Zone.EXILE)
    _turn(engine, 1)
    assert continuous.cast_prohibited(engine.state, opponent, bolt, Zone.GRAVEYARD)
    _turn(engine, 0)
    assert not continuous.cast_prohibited(engine.state, opponent, bolt, Zone.GRAVEYARD)


def test_reflector_mage_restricts_the_bounced_creatures_owner_only():
    engine = _engine(3)
    _turn(engine, 0)
    target = _put(engine, _bear("Named creature"), "p2")
    target.controller_id = "p3"
    _cast_real(engine, "Reflector Mage")
    engine.resolve_pending_choice(str(target.instance_id))
    assert target.zone == Zone.HAND
    caster, owner, other = engine.state.players
    assert continuous.cast_prohibited(engine.state, owner, target.card)
    assert not continuous.cast_prohibited(engine.state, owner, _bear("Other creature"))
    assert not continuous.cast_prohibited(engine.state, caster, target.card)
    assert not continuous.cast_prohibited(engine.state, other, target.card)

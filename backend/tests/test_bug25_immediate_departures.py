"""RULE 800.4a: real three-player departures, control and independent history."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import GameContext, GainControlUntilEndOfTurnEffect, ExchangeControlEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState, StackItem, TurnControl
from mtg_analyzer.models.game.player import Player


def engine():
    state = GameState([Player(id=pid, life=20) for pid in ("a", "b", "c")])
    state.current_step = "main1"
    state.current_phase = "precombat_main"
    state.internal_turn.number = 1
    state.priority_player_index = 0
    return GameEngine(state)


def permanent(eng, owner, name="Bear", controller=None, **card_fields):
    card = Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
                power=2, toughness=2, **card_fields)
    obj = GameObject(card, owner_id=owner, controller_id=controller, zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def steal(eng, obj, taker, duration="permanent", **kwargs):
    source = permanent(eng, taker, name=f"Source {taker}")
    effect = GainControlUntilEndOfTurnEffect(source=source, duration=duration, **kwargs)
    effect.apply(GameContext(eng.state, eng.rules), [obj])
    return source


@pytest.mark.parametrize("loss", ["concede", "life"])
def test_owned_objects_leave_all_zones_immediately_and_steals_leave_with_owner(loss):
    eng = engine()
    obj = permanent(eng, "b", controller="c")
    player = eng.state.player_by_id("b")
    for zone in Player.PERSONAL_ZONES:
        player.add_to_zone(GameObject(Card(id=str(zone), name=str(zone), type_line="Land"), "b"), zone)
    if loss == "concede":
        eng.rules.concede(player)
    else:
        player.life = 0
        eng.rules.check_state_based_actions()
    assert obj not in eng.state.battlefield
    assert all(not player.zones[zone] for zone in Player.PERSONAL_ZONES)
    assert eng.state.pending_leave_ids == []
    assert not eng.state.game_over
    assert eng.state.internal_turn.number == 1


@pytest.mark.parametrize("duration", ["permanent", "end_of_turn", "end_of_your_next_turn"])
def test_control_effects_end_but_bribery_style_entry_controller_is_exiled(duration):
    eng = engine()
    stolen = permanent(eng, "a", name="Stolen")
    bribed = permanent(eng, "a", name="Bribed", controller="b")
    steal(eng, stolen, "b", duration)
    eng.rules.concede(eng.state.player_by_id("b"))
    assert stolen in eng.state.battlefield and stolen.controller_id == "a"
    assert bribed not in eng.state.battlefield
    assert bribed in eng.state.player_by_id("a").exile
    assert not stolen.control_effects
    eng._step_cleanup()
    assert stolen.controller_id == "a"


def test_overlap_does_not_resurrect_departed_middle_controller():
    eng = engine()
    obj = permanent(eng, "a")
    steal(eng, obj, "b", "permanent")
    steal(eng, obj, "c", "end_of_turn")
    clone = eng.state.clone()
    eng.rules.concede(eng.state.player_by_id("b"))
    assert obj.controller_id == "c"
    eng._step_cleanup()
    assert obj.controller_id == "a"
    assert clone.find_object(obj.instance_id).control_effects[0]["controller_id"] == "b"


def test_bribery_original_controller_who_left_is_exiled_when_later_control_expires():
    eng = engine()
    obj = permanent(eng, "a", controller="b")
    steal(eng, obj, "c", "end_of_turn")
    eng.rules.concede(eng.state.player_by_id("b"))
    assert obj in eng.state.battlefield and obj.controller_id == "c"
    eng._step_cleanup()
    assert obj in eng.state.player_by_id("a").exile


def test_exchange_control_effects_end_when_recipient_departs():
    eng = engine()
    mine = permanent(eng, "a", name="Mine")
    theirs = permanent(eng, "b", name="Theirs")
    ExchangeControlEffect(source=mine).apply(GameContext(eng.state, eng.rules), [theirs])
    assert mine.controller_id == "b" and theirs.controller_id == "a"
    eng.rules.concede(eng.state.player_by_id("b"))
    assert mine in eng.state.battlefield and mine.controller_id == "a"
    assert theirs not in eng.state.battlefield


def test_stack_abilities_follow_controller_not_source_owner_and_stolen_spell_reverts():
    eng = engine()
    owned = permanent(eng, "b", name="Departing source")
    borrowed = permanent(eng, "a", name="Surviving source", controller="b")
    survivor_ability = StackItem("ability", "a", source=owned)
    departed_ability = StackItem("ability", "b", source=borrowed)
    card = GameObject(Card(id="spell", name="Spell", type_line="Instant", is_instant=True), "a", zone=Zone.STACK)
    stolen_spell = StackItem("spell", "a", obj=card)
    copied = GameObject(card.card, "a", zone=Zone.STACK)
    copied.is_token = True
    departed_copy = StackItem("spell", "b", obj=copied)
    eng.state.stack[:] = [survivor_ability, departed_ability, stolen_spell, departed_copy]
    eng.rules.gain_control_of_spell(stolen_spell, "b")
    eng.rules.concede(eng.state.player_by_id("b"))
    assert eng.state.stack == [survivor_ability, stolen_spell]
    assert stolen_spell.controller_id == card.controller_id == "a"


def test_priority_passes_to_next_living_seat_and_active_turn_continues():
    eng = engine()
    eng.state.priority_passed = {"c"}
    eng.rules.concede(eng.state.player_by_id("a"))
    assert eng.state.priority_player.id == "b"
    assert eng.state.active_player.id == "a"
    assert eng.state.internal_turn.number == 1
    assert eng.state.priority_passed == {"c"}


def test_departing_controller_stops_controlling_other_players():
    eng = engine()
    active = TurnControl(controlled_id="a", controller_id="b", install_turn=1)
    active.phase = "active"
    waiting = TurnControl(controlled_id="c", controller_id="b", install_turn=1)
    eng.state.turn_controls[:] = [active, waiting]
    assert eng.state.decider_for("a") == "b"
    eng.state.word_of_command = {"controller_id": "b", "target_id": "c"}
    assert eng.state.decider_for("c") == "b"
    eng.rules.concede(eng.state.player_by_id("b"))
    assert eng.state.turn_controls == []
    assert eng.state.word_of_command is None
    assert eng.state.decider_for("a") == "a"


def test_active_departing_monarch_and_initiative_pass_immediately_to_next_living_seat():
    eng = engine()
    eng.state.monarch_id = eng.state.initiative_id = "a"
    eng.rules.concede(eng.state.player_by_id("a"))
    assert eng.state.monarch_id == eng.state.initiative_id == "b"


@pytest.mark.parametrize("later", ["permanent", "end_of_your_next_turn"])
def test_expiration_never_revives_an_old_controller_on_second_cleanup(later):
    eng = engine()
    obj = permanent(eng, "a")
    steal(eng, obj, "b", "end_of_turn")
    steal(eng, obj, "c", later)
    eng._step_cleanup()
    assert obj.controller_id == "c"
    eng._step_cleanup()
    assert obj.controller_id == "c"
    assert obj.control_change_until_eot is None


def test_actual_act_of_treason_binds_casts_and_reverts_immediately_on_concession():
    eng = engine()
    player = eng.state.player_by_id("a")
    bear = permanent(eng, "b")
    card = Card(id="act", name="Act of Treason", type_line="Sorcery", is_sorcery=True,
                mana_cost_string="{2}{R}", converted_mana_cost=3,
                oracle_text="Gain control of target creature until end of turn. Untap that creature. It gains haste until end of turn.")
    spell = GameObject(card, "a", zone=Zone.HAND)
    player.add_to_zone(spell, Zone.HAND)
    bind_from_catalogue(spell)
    assert spell.spell_effects
    player.mana_pool.add_many({"R": 1, "C": 2})
    eng.cast_spell(player, spell, targets=[bear])
    eng.resolve_until_stable()
    assert bear.controller_id == "a" and not bear.tapped
    eng.rules.concede(player)
    assert bear in eng.state.battlefield and bear.controller_id == "b"


def test_actual_mind_control_aura_leaves_and_surviving_creature_reverts():
    eng = engine()
    bear = permanent(eng, "a")
    card = Card(id="mind", name="Mind Control", type_line="Enchantment — Aura",
                oracle_text="Enchant creature\nYou control enchanted creature.")
    aura = GameObject(card, "b", zone=Zone.BATTLEFIELD)
    aura.attached_to = bear.instance_id
    eng.state.add_to_battlefield(aura)
    bind_from_catalogue(aura)
    assert aura.static_effects
    eng.recompute_continuous_effects()
    assert bear.controller_id == "b"
    eng.rules.concede(eng.state.player_by_id("b"))
    assert aura not in eng.state.battlefield
    assert bear in eng.state.battlefield and bear.controller_id == "a"


def test_terminal_concession_changes_live_board_but_history_rewinds_independently():
    from mtg_analyzer.services.game_session import GameSessionManager
    land = Card(id="forest", name="Forest", type_line="Basic Land — Forest", is_land=True)
    session = GameSessionManager().create_multiplayer([
        {"player_id": pid, "name": pid, "library": [land] * 30} for pid in ("a", "b")])
    for pid in ("a", "b"):
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id=pid)
    obj = permanent(session.engine, "b")
    session.concede("b")
    assert obj not in session.engine.state.battlefield
    snapshot = session._history[-1][1]
    assert snapshot.find_object(obj.instance_id) is not obj
    assert snapshot.find_object(obj.instance_id) in snapshot.battlefield
    session.rewind(1)
    assert session.engine.state.find_object(obj.instance_id) in session.engine.state.battlefield
    assert not session.engine.state.player_by_id("b").has_lost


def test_later_floating_control_overrides_older_aura_and_exposes_it_on_expiry():
    eng = engine()
    bear = permanent(eng, "a")
    card = Card(id="mind", name="Mind Control", type_line="Enchantment — Aura",
                oracle_text="Enchant creature\nYou control enchanted creature.")
    aura = GameObject(card, "b", zone=Zone.BATTLEFIELD)
    aura.attached_to = bear.instance_id
    eng.state.add_to_battlefield(aura)
    bind_from_catalogue(aura)
    eng.recompute_continuous_effects()
    assert bear.controller_id == "b"
    steal(eng, bear, "c", "end_of_turn")
    eng.recompute_continuous_effects()
    assert bear.controller_id == "c"
    eng.rules.concede(eng.state.player_by_id("b"))
    assert bear.controller_id == "c"
    eng._step_cleanup()
    assert bear.controller_id == "a"


def test_older_floating_control_is_restored_after_later_aura_owner_departs():
    eng = engine()
    bear = permanent(eng, "a")
    steal(eng, bear, "c", "end_of_turn")
    card = Card(id="mind", name="Mind Control", type_line="Enchantment — Aura",
                oracle_text="Enchant creature\nYou control enchanted creature.")
    aura = GameObject(card, "b", zone=Zone.BATTLEFIELD)
    aura.attached_to = bear.instance_id
    eng.state.add_to_battlefield(aura)
    bind_from_catalogue(aura)
    eng.recompute_continuous_effects()
    assert bear.controller_id == "b"
    eng.rules.concede(eng.state.player_by_id("b"))
    assert bear.controller_id == "c"
    eng._step_cleanup()
    assert bear.controller_id == "a"


def test_source_bound_grant_ends_if_source_owner_leaves_under_another_controller():
    eng = engine()
    bear = permanent(eng, "a")
    source = steal(eng, bear, "b", "permanent", while_source="on_battlefield")
    assert bear.control_change_while_source
    source.owner_id = "c"
    eng.rules.concede(eng.state.player_by_id("c"))
    assert bear.controller_id == "a"
    assert bear.control_change_while_source is None


def test_two_overlapping_auras_restore_original_controller_without_intermediate_stale_base():
    eng = engine()
    bear = permanent(eng, "a")
    for owner in ("b", "c"):
        card = Card(id=f"mind{owner}", name="Mind Control", type_line="Enchantment — Aura",
                    oracle_text="Enchant creature\nYou control enchanted creature.")
        aura = GameObject(card, owner, zone=Zone.BATTLEFIELD)
        aura.attached_to = bear.instance_id
        eng.state.add_to_battlefield(aura)
        bind_from_catalogue(aura)
    eng.recompute_continuous_effects()
    assert bear.controller_id == "c"
    eng.rules.concede(eng.state.player_by_id("c"))
    assert bear.controller_id == "b"
    eng.rules.concede(eng.state.player_by_id("b"))
    assert bear.controller_id == "a"


def test_departing_owned_anthem_stops_affecting_survivors_immediately():
    eng = engine()
    bear = permanent(eng, "a")
    card = Card(id="anthem", name="Glorious Anthem", type_line="Enchantment",
                oracle_text="Creatures you control get +1/+1.")
    anthem = GameObject(card, "b", controller_id="a", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(anthem)
    bind_from_catalogue(anthem)
    eng.recompute_continuous_effects()
    assert bear.power == bear.toughness == 3
    eng.rules.concede(eng.state.player_by_id("b"))
    assert bear.power == bear.toughness == 2

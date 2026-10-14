"""PAR-118 - "exile a card from your hand with a number of time counters on it equal to its mana value" (RULE 702.62).

The Eleventh Doctor (combat-damage trigger, optional, suspend if missing), The Wedding of River Song (draw, optional
nonland pick, then the targeted opponent does the same, both gain suspend) and Alaundo the Seer (tap: draw, forced
pick, per-owner sweep of the other exiled cards). Executed against the real engine with the real cached cards.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.services.card_database import DEFAULT_DB_PATH, CardDatabase

CARDS = ("Alaundo the Seer", "The Eleventh Doctor", "The Wedding of River Song")


def _db_card(name):
    return CardDatabase(DEFAULT_DB_PATH).get_card(name)


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.state.current_step = "main1"
    for pid in ("p1", "p2"):
        for i in range(10):
            eng.state.player_by_id(pid).library.append(GameObject(
                Card(id=f"{pid}L{i}", name=f"Lib{i}", type_line="Instant", is_instant=True, converted_mana_cost=1),
                owner_id=pid, zone=Zone.LIBRARY))
    return eng


def _put(eng, card, owner, zone):
    obj = GameObject(card, owner_id=owner, zone=zone)
    obj.controller_id = owner
    bind_from_catalogue(obj)
    player = eng.state.player_by_id(owner)
    if zone == Zone.BATTLEFIELD:
        obj.summoning_sick = False
        eng.state.add_to_battlefield(obj)
    elif zone == Zone.HAND:
        player.hand.append(obj)
    elif zone == Zone.EXILE:
        player.exile.append(obj)
    return obj


def _spell(name, cmc, land=False):
    return Card(id=name, name=name, type_line="Land" if land else "Sorcery", is_land=land, is_sorcery=not land,
                converted_mana_cost=cmc, mana_cost_string="" if land else "{%d}" % cmc)


def _creature(name, cmc):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True, power=2, toughness=2,
                converted_mana_cost=cmc, mana_cost_string="{%d}" % cmc)


def test_all_three_cards_modeled():
    for name in CARDS:
        assert parse_oracle(_db_card(name)).coverage == MODELED, name


def _doctor_hit(eng, doctor):
    p2 = eng.state.player_by_id("p2")
    eng._apply_combat_damage([(p2, 2, doctor)])
    eng.resolve_until_stable()


def test_eleventh_doctor_exiles_with_mana_value_counters_and_grants_suspend():
    eng = _engine()
    doctor = _put(eng, _db_card("The Eleventh Doctor"), "p1", Zone.BATTLEFIELD)
    big = _put(eng, _spell("Big", 4), "p1", Zone.HAND)
    _put(eng, _spell("Small", 1), "p1", Zone.HAND)
    _doctor_hit(eng, doctor)
    assert eng.state.pending_choice["kind"] == "trigger_target"  # the "you may" prompt
    eng.resolve_pending_choice("do")
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice["kind"] == "choose_objects" and choice["player_id"] == "p1"
    eng.resolve_pending_choice(str(big.instance_id))
    eng.resolve_until_stable()
    assert big.zone == Zone.EXILE and big.counters.get("time") == 4 and big.granted_suspend
    assert big not in eng.state.player_by_id("p1").hand


def test_granted_suspend_card_loses_a_counter_each_upkeep_then_casts_free():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    card = _put(eng, _creature("Bear", 2), "p1", Zone.EXILE)
    card.add_counters("time", 2)
    card.granted_suspend = True
    for expected in (1, 0):
        eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep"))
        eng.resolve_until_stable()
        assert card.counters.get("time", 0) == expected
    # the last counter is gone: the free cast (with haste) is offered from exile
    assert card.instance_id in eng.state.free_cast_instance_ids and card.granted_suspend_haste
    eng.cast_spell(p1, card)
    eng.resolve_until_stable()
    assert card in eng.state.battlefield and not p1.mana_pool.total()


def test_wedding_both_players_pick_nonland_and_gain_suspend():
    eng = _engine()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    wedding = _put(eng, _db_card("The Wedding of River Song"), "p1", Zone.HAND)
    mine = _put(eng, _spell("Mine", 3), "p1", Zone.HAND)
    land = _put(eng, _spell("Forest", 0, land=True), "p1", Zone.HAND)
    theirs = _put(eng, _spell("Theirs", 2), "p2", Zone.HAND)
    their_land = _put(eng, _spell("Island", 0, land=True), "p2", Zone.HAND)
    p1.mana_pool.add("W", 3)
    eng.cast_spell(p1, wedding, targets=[p2])
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice["kind"] == "choose_objects" and choice["player_id"] == "p1"
    offered = {o.get("instance_id") for o in choice["options"]}
    assert land.instance_id not in offered and mine.instance_id in offered
    eng.resolve_pending_choice(str(mine.instance_id))
    # the targeted opponent answers their own pick, lands excluded
    choice = eng.state.pending_choice
    assert choice["kind"] == "choose_objects" and choice["player_id"] == "p2"
    offered = {o.get("instance_id") for o in choice["options"]}
    assert their_land.instance_id not in offered
    eng.resolve_pending_choice(str(theirs.instance_id))
    eng.resolve_until_stable()
    # The Wedding's own "Time travel." then removes one counter from the caster's suspended card (3 -> 2); the
    # opponent's card is not the caster's to time travel.
    assert mine.zone == Zone.EXILE and mine.counters.get("time") == 2 and mine.granted_suspend
    assert theirs.zone == Zone.EXILE and theirs.counters.get("time") == 2 and theirs.granted_suspend
    assert land in p1.hand and their_land in p2.hand


def test_wedding_opponent_still_picks_when_controller_declines():
    eng = _engine()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    wedding = _put(eng, _db_card("The Wedding of River Song"), "p1", Zone.HAND)
    mine = _put(eng, _spell("Mine", 3), "p1", Zone.HAND)
    theirs = _put(eng, _spell("Theirs", 2), "p2", Zone.HAND)
    p1.mana_pool.add("W", 3)
    eng.cast_spell(p1, wedding, targets=[p2])
    eng.resolve_until_stable()
    eng.resolve_pending_choice("decline")
    choice = eng.state.pending_choice
    assert choice["kind"] == "choose_objects" and choice["player_id"] == "p2"
    eng.resolve_pending_choice(str(theirs.instance_id))
    eng.resolve_until_stable()
    assert mine.zone == Zone.HAND and not mine.counters
    assert theirs.zone == Zone.EXILE and theirs.counters.get("time") == 2 and theirs.granted_suspend


def test_alaundo_exiles_without_suspend_and_sweeps_other_cards():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    alaundo = _put(eng, _db_card("Alaundo the Seer"), "p1", Zone.BATTLEFIELD)
    older = _put(eng, _creature("Older", 2), "p1", Zone.EXILE)
    older.add_counters("time", 2)
    other = _put(eng, _spell("Foreign", 2), "p2", Zone.EXILE)
    other.add_counters("time", 2)
    for obj in list(p1.hand):
        p1.hand.remove(obj)
    keep = _put(eng, _spell("Keep", 5), "p1", Zone.HAND)
    eng.activate_ability(p1, alaundo, 0)
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice["kind"] == "choose_objects" and choice["player_id"] == "p1"
    eng.resolve_pending_choice(str(keep.instance_id))
    eng.resolve_until_stable()
    assert keep.zone == Zone.EXILE and keep.counters.get("time") == 5 and not keep.granted_suspend
    assert older.counters.get("time") == 1  # swept once
    assert other.counters.get("time") == 2  # not owned by Alaundo's controller


def test_alaundo_last_counter_removed_opens_free_cast_with_haste():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    alaundo = _put(eng, _db_card("Alaundo the Seer"), "p1", Zone.BATTLEFIELD)
    older = _put(eng, _creature("Older", 1), "p1", Zone.EXILE)
    older.add_counters("time", 1)
    for obj in list(p1.hand):
        p1.hand.remove(obj)
    keep = _put(eng, _creature("Keep", 3), "p1", Zone.HAND)
    eng.activate_ability(p1, alaundo, 0)
    eng.resolve_until_stable()
    eng.resolve_pending_choice(str(keep.instance_id))
    eng.resolve_until_stable()
    assert older.counters.get("time", 0) == 0
    assert older.instance_id in eng.state.free_cast_instance_ids and older.granted_suspend_haste
    assert keep.counters.get("time") == 3 and keep.instance_id not in eng.state.free_cast_instance_ids


def test_alaundo_with_an_empty_hand_still_sweeps():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    p1.library.clear()  # the draw finds nothing
    alaundo = _put(eng, _db_card("Alaundo the Seer"), "p1", Zone.BATTLEFIELD)
    older = _put(eng, _spell("Older", 2), "p1", Zone.EXILE)
    older.add_counters("time", 2)
    eng.activate_ability(p1, alaundo, 0)
    eng.resolve_until_stable()
    assert older.counters.get("time") == 1

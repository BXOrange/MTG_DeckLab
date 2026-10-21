"""BUG-22: RULE 120.3f/615.1/702.2b -- combat consequences come from damage actually dealt.

Lifelink gain, the deathtouch lethal mark and the aggregate "one or more creatures deal combat damage
to a player" event are derived from receipts (source, recipient, amount dealt) written by the shared
successful-damage path, not from the pre-prevention combat assignments.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone

START_LIFE = 20
POWER = 3
PARTIAL_PREVENTION = 2
SECOND_ATTACKER_POWER = 2


def _creature(name, power, toughness, *keywords):
    return Card(id=name, name=name, type_line="Creature — Test", is_creature=True, power=power,
                toughness=toughness, keywords=list(keywords), mana_cost_string="{1}",
                converted_mana_cost=1)


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])],
                              starting_life=START_LIFE, starting_hand=0)
    eng.start()
    while eng.state.current_step != "declare_attackers":
        eng.advance_step()
    return eng


def _put(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _attack(eng, attackers, blocker=None):
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    eng.declare_attackers(p1, list(attackers))
    eng.advance_step()
    eng.declare_blockers(p2, [{"blocker": blocker, "attacker": attackers[0]}] if blocker else [])


def _events(eng, event_type):
    return [e for e in eng.state.event_log if e.type == event_type]


def _life(eng, pid):
    return eng.state.player_by_id(pid).life


def _run_damage(eng):
    while eng.state.current_step not in ("combat_damage", "end_combat"):
        eng.advance_step()


def test_fog_grants_no_lifelink_and_no_player_hit_event():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    atk = _put(eng, _creature("Vamp", POWER, POWER, "Lifelink"))
    eng.rules.prevent_all_combat_damage_this_turn(p1)
    _attack(eng, [atk])
    _run_damage(eng)
    assert _life(eng, "p2") == START_LIFE
    assert _life(eng, "p1") == START_LIFE
    assert not _events(eng, EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER)
    assert not [e for e in _events(eng, EventType.DAMAGE) if e.get("is_player")]


def test_partial_prevention_gains_only_damage_dealt():
    eng = _engine()
    atk = _put(eng, _creature("Vamp", POWER, POWER, "Lifelink"))
    eng.rules.prevent_damage_to_player(eng.state.player_by_id("p2"), PARTIAL_PREVENTION)
    _attack(eng, [atk])
    _run_damage(eng)
    dealt = POWER - PARTIAL_PREVENTION
    assert _life(eng, "p2") == START_LIFE - dealt
    assert _life(eng, "p1") == START_LIFE + dealt
    (agg,) = _events(eng, EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER)
    assert agg.get("amount") == dealt


def test_prevented_deathtouch_hit_does_not_kill_a_creature_with_old_damage():
    eng = _engine()
    atk = _put(eng, _creature("Snake", 1, 1, "Deathtouch"))
    blocker = _put(eng, _creature("Wall", 0, 4), "p2")
    blocker.damage_marked = 1
    eng.rules.prevent_damage_from_source(atk)
    _attack(eng, [atk], blocker)
    _run_damage(eng)
    assert blocker in eng.state.battlefield
    assert not blocker.dealt_deathtouch_damage


def test_unprevented_deathtouch_and_lifelink_still_work():
    eng = _engine()
    atk = _put(eng, _creature("Nighthawk", 2, 3, "Deathtouch", "Lifelink"))
    blocker = _put(eng, _creature("Wall", 0, 9), "p2")
    _attack(eng, [atk], blocker)
    _run_damage(eng)
    assert blocker not in eng.state.battlefield
    assert _life(eng, "p1") == START_LIFE + 2


def test_redirected_damage_follows_actual_recipient():
    eng = _engine()
    atk = _put(eng, _creature("Vamp", POWER, POWER, "Lifelink"))
    bear = _put(eng, _creature("Bear", 2, 9), "p2")
    eng.rules.redirect_damage_from_source(atk, bear)
    _attack(eng, [atk])
    _run_damage(eng)
    assert _life(eng, "p2") == START_LIFE
    assert bear.damage_marked == POWER
    assert _life(eng, "p1") == START_LIFE + POWER
    assert not _events(eng, EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER)


def test_double_strike_lifelink_gains_each_step():
    eng = _engine()
    atk = _put(eng, _creature("Duelist", 2, 2, "Double strike", "Lifelink"))
    _attack(eng, [atk])
    eng.advance_step()
    assert _life(eng, "p1") == START_LIFE + 2
    eng.advance_step()
    assert _life(eng, "p1") == START_LIFE + 4
    assert len(_events(eng, EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER)) == 2


def test_aggregate_event_counts_only_hits_that_dealt_damage():
    eng = _engine()
    a = _put(eng, _creature("Vamp", POWER, POWER, "Lifelink"))
    b = _put(eng, _creature("Bear", SECOND_ATTACKER_POWER, 2))
    eng.rules.prevent_damage_from_source(a)
    _attack(eng, [a, b])
    _run_damage(eng)
    assert _life(eng, "p1") == START_LIFE
    (agg,) = _events(eng, EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER)
    assert agg.get("contributor_ids") == [b.instance_id]
    assert agg.get("amount") == SECOND_ATTACKER_POWER


def test_replacement_choice_pause_counts_receipts_exactly_once():
    eng = _engine()
    p2 = eng.state.player_by_id("p2")
    a = _put(eng, _creature("Vamp", POWER, POWER, "Lifelink"))
    b = _put(eng, _creature("Bear", SECOND_ATTACKER_POWER, 2))
    eng.rules.prevent_damage_to_player(p2, 1)
    eng.rules.prevent_damage_to_player(p2, 1)
    _attack(eng, [a, b])
    _run_damage(eng)
    guard = 0
    while eng.state.pending_choice and guard < 10:
        assert eng.state.pending_choice.get("kind") == "replacement_order"
        assert not _events(eng, EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER), "finalised too early"
        eng.rules.resolve_choice(0)
        guard += 1
    assert guard, "the test must actually pause on a replacement choice"
    # While the lifelinker's hit is suspended the Bear's hit (no second choice may open) uses up both
    # 1-point shields, so the resumed lifelink hit lands in full: one settle, counted exactly once.
    assert _life(eng, "p2") == START_LIFE - POWER
    assert _life(eng, "p1") == START_LIFE + POWER
    (agg,) = _events(eng, EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER)
    assert agg.get("amount") == POWER
    assert agg.get("contributor_ids") == [a.instance_id]
    assert eng.state.combat_damage_batch is None

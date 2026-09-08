"""Blight Curse batch C5 wave 8 — Lasting Tarfire
(hand-authored, `ability_catalogue/entries_017.py`).

* Lasting Tarfire — "At the beginning of each end step, if you put a counter
  on a creature this turn, this enchantment deals 2 damage to each opponent."
  New per-turn tracker `GameState.counter_placed_on_creature_this_turn` (a
  causer-id set), populated in `RulesEngine.add_counters`'s post-replacement
  `_finish` and cleared in `GameEngine.begin_turn`; read by the new
  `static_conditions` kind ``you_placed_counter_on_creature_this_turn`` as a
  trigger-level RULE 603.4 intervening-if.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import specs_for
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


LASTING_TARFIRE = Card(
    id="LT", name="Lasting Tarfire", type_line="Enchantment",
    oracle_text="At the beginning of each end step, if you put a counter on a "
                "creature this turn, this enchantment deals 2 damage to each opponent.",
)


def _setup(eng):
    lt = GameObject(LASTING_TARFIRE, owner_id="p1", zone=Zone.BATTLEFIELD)
    lt.controller_id = "p1"
    eng.state.add_to_battlefield(lt)
    bind_from_catalogue(lt)
    creature = GameObject(Card(id="C", name="C", type_line="Creature — Ox",
                               is_creature=True, power=3, toughness=3),
                          owner_id="p1", zone=Zone.BATTLEFIELD)
    creature.controller_id = "p1"
    eng.state.add_to_battlefield(creature)
    eng.begin_turn()
    return lt, creature


def _fire_end_step(eng):
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", player_id="p1"))
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()


def test_lasting_tarfire_authored_each_end_step_trigger():
    specs = specs_for(LASTING_TARFIRE)
    trg = [s for s in specs if s.ability_kind == "triggered"]
    assert len(trg) == 1
    assert trg[0].trigger["event"] == "STEP_BEGIN"
    assert trg[0].trigger["active_if"]["kind"] == "you_placed_counter_on_creature_this_turn"


def test_deals_2_to_each_opponent_when_a_counter_was_placed():
    eng = _engine()
    lt, creature = _setup(eng)
    p2 = eng.state.players[1]

    eng.rules.add_counters(creature, 1, "-1/-1", source=lt)
    assert "p1" in eng.state.counter_placed_on_creature_this_turn

    _fire_end_step(eng)
    assert p2.life == 18


def test_no_damage_when_no_counter_placed_this_turn():
    eng = _engine()
    lt, creature = _setup(eng)
    p2 = eng.state.players[1]

    _fire_end_step(eng)
    assert p2.life == 20
    assert not eng.state.stack


def test_tracker_resets_between_turns():
    eng = _engine()
    lt, creature = _setup(eng)
    p2 = eng.state.players[1]

    eng.rules.add_counters(creature, 1, "-1/-1", source=lt)
    eng.begin_turn()  # new turn — flag cleared
    assert "p1" not in eng.state.counter_placed_on_creature_this_turn

    _fire_end_step(eng)
    assert p2.life == 20


def test_opponents_counter_placement_does_not_arm_your_tarfire():
    eng = _engine()
    lt, creature = _setup(eng)
    p2 = eng.state.players[1]

    opp_src = GameObject(Card(id="OS", name="OppSrc", type_line="Artifact"),
                         owner_id="p2", zone=Zone.BATTLEFIELD)
    opp_src.controller_id = "p2"
    eng.state.add_to_battlefield(opp_src)
    eng.rules.add_counters(creature, 1, "-1/-1", source=opp_src)  # p2 is the causer

    _fire_end_step(eng)
    assert p2.life == 20  # p1 (Tarfire's controller) placed nothing

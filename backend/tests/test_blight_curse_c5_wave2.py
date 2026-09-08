"""Blight Curse batch C5 wave 2 — Midnight Banshee / Blowfly Infestation
(hand-authored, `ability_catalogue/entries_017.py`).

* Midnight Banshee: upkeep ``add_counters`` mass selector
  (``"each_creature"``) narrowed by ``creature_filter={"without_color":
  "B"}`` — the mass-selector loop now honours `matches_object_filter` the
  same way the single-target branch does.
* Blowfly Infestation: "Whenever a creature dies, **if it had a -1/-1
  counter on it**, put a -1/-1 counter on target creature." — the RULE
  603.4 intervening-if is a *trigger-level* predicate (`effect_binder`'s
  ``dying_had_counter``), so an untriggered ability never even prompts for
  a target. Massacre Girl's ``dying_toughness_below`` is the sibling.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.api.dependencies import get_card_database
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


def _c(eng, name, pid, mana="", power=2, toughness=2):
    o = GameObject(Card(id=name[:6], name=name, type_line="Creature — Rat", is_creature=True,
                        power=power, toughness=toughness, mana_cost_string=mana),
                   owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    eng.state.add_to_battlefield(o)
    return o


MIDNIGHT_BANSHEE = Card(
    id="MDB", name="Midnight Banshee", type_line="Creature — Spirit", is_creature=True,
    power=4, toughness=4, keywords=["Wither"], mana_cost_string="{3}{B}{B}{B}",
    oracle_text="Wither\nAt the beginning of your upkeep, put a -1/-1 counter on each "
                "nonblack creature.",
)
BLOWFLY_INFESTATION = Card(
    id="BFI", name="Blowfly Infestation", type_line="Enchantment",
    oracle_text="Whenever a creature dies, if it had a -1/-1 counter on it, put a -1/-1 "
                "counter on target creature.",
)


def test_both_authored():
    assert specs_for(MIDNIGHT_BANSHEE) and specs_for(BLOWFLY_INFESTATION)


def test_midnight_banshee_upkeep_hits_nonblack_only():
    # Real cached cards — a bare `Card(mana_cost_string=…)` fixture carries
    # no `colors`, so the "nonblack" (`without_color`) filter needs Scryfall
    # colour data.
    db = get_card_database()
    wc = db.get_card("Savannah Lions")
    bc = db.get_card("Vampire Nighthawk")
    if wc is None or bc is None:
        pytest.skip("colour reference cards not cached")

    eng = _engine()
    mb = GameObject(MIDNIGHT_BANSHEE, owner_id="p1", zone=Zone.BATTLEFIELD)
    mb.controller_id = "p1"
    eng.state.add_to_battlefield(mb)
    bind_from_catalogue(mb)

    white = GameObject(wc, owner_id="p2", zone=Zone.BATTLEFIELD)
    white.controller_id = "p2"
    black = GameObject(bc, owner_id="p2", zone=Zone.BATTLEFIELD)
    black.controller_id = "p2"
    eng.state.add_to_battlefield(white)
    eng.state.add_to_battlefield(black)
    eng.recompute_continuous_effects()
    eng.begin_turn()

    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", player_id="p1"))
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()

    assert white.counters.get("-1/-1", 0) == 1   # Savannah Lions is white
    assert black.counters.get("-1/-1", 0) == 0   # Vampire Nighthawk is black


def test_blowfly_does_not_trigger_or_prompt_without_a_counter():
    eng = _engine()
    bf = GameObject(BLOWFLY_INFESTATION, owner_id="p1", zone=Zone.BATTLEFIELD)
    bf.controller_id = "p1"
    eng.state.add_to_battlefield(bf)
    bind_from_catalogue(bf)
    _c(eng, "Target", "p1", power=3, toughness=3)
    doomed = _c(eng, "Doomed", "p2", power=1, toughness=1)  # no counter
    eng.begin_turn()

    eng.rules.destroy(doomed)
    eng.rules.put_triggers_on_stack()
    assert not eng.state.pending_choice
    assert not eng.state.stack


def test_blowfly_triggers_when_the_dead_creature_had_a_minus_counter():
    eng = _engine()
    bf = GameObject(BLOWFLY_INFESTATION, owner_id="p1", zone=Zone.BATTLEFIELD)
    bf.controller_id = "p1"
    eng.state.add_to_battlefield(bf)
    bind_from_catalogue(bf)
    target = _c(eng, "Target", "p1", power=3, toughness=3)
    doomed = _c(eng, "Doomed", "p2", power=1, toughness=1)
    doomed.counters["-1/-1"] = 1
    eng.begin_turn()

    eng.rules.destroy(doomed)
    eng.rules.put_triggers_on_stack()
    pc = eng.state.pending_choice
    assert pc and pc["kind"] == "trigger_target"
    assert pc["options"][0]["instance_id"] == target.instance_id

"""Blight Curse batch C5 wave 1 — Binding the Old Gods / Massacre Girl,
Known Killer / Dusk Urchins.

* `_destroy`'s guard tuple gained ``nonland_permanent`` /
  ``nonland_permanent_you_control`` / ``nonland_permanent_you_dont_control``
  (Binding the Old Gods' chapter I; `targeting.legal_targets` already had
  the branches).
* `ConditionalEffect` key ``dying_creature_toughness_below`` + a
  ``toughness`` snapshot on the DIES event (Massacre Girl).
* `DrawCardEffect.count_from_trigger_event_counter` — a named counter kind
  off the DIES event's ``counters`` snapshot (Dusk Urchins).
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import specs_for
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _lib(eng, pid, n=9):
    p = eng.state.player_by_id(pid)
    for i in range(n):
        p.library.append(GameObject(Card(id=f"L{pid}{i}", name=f"L{i}", type_line="Plains",
                                         is_land=True), owner_id=pid, zone=Zone.LIBRARY))


# --- Binding the Old Gods -----------------------------------------------------


def test_destroy_nonland_permanent_an_opponent_controls_parses():
    assert match_clause("destroy target nonland permanent an opponent controls") == [
        EffectSpec("destroy", {"target_kind": "nonland_permanent_you_dont_control"})
    ]


def test_binding_the_old_gods_is_fully_modeled():
    c = Card(id="BOG", name="Binding the Old Gods", type_line="Enchantment — Saga",
             oracle_text="(As this Saga enters and after your draw step, add a lore counter. "
                         "Sacrifice after III.)\nI — Destroy target nonland permanent an opponent "
                         "controls.\nII — Search your library for a Forest card, put it onto the "
                         "battlefield tapped, then shuffle.\nIII — Creatures you control gain "
                         "deathtouch until end of turn.")
    assert parse_oracle(c).coverage != UNMODELED, parse_oracle(c).unclaimed


# --- Massacre Girl, Known Killer --------------------------------------------

MASSACRE_GIRL = Card(
    id="MG", name="Massacre Girl, Known Killer",
    type_line="Legendary Creature — Human Assassin", is_creature=True, power=4, toughness=4,
    keywords=["Menace"],
    oracle_text="Menace\nCreatures you control have wither.\nWhenever a creature an opponent "
                "controls dies, if its toughness was less than 1, draw a card.",
)


def test_massacre_girl_authored_three_specs():
    assert len(specs_for(MASSACRE_GIRL)) == 3  # wither anthem + dies trigger + Menace kw


def test_draw_only_when_the_dead_opponent_creature_had_toughness_below_1():
    eng = _engine()
    p1 = eng.state.players[0]
    mg = GameObject(MASSACRE_GIRL, owner_id="p1", zone=Zone.BATTLEFIELD)
    mg.controller_id = "p1"
    eng.state.add_to_battlefield(mg)
    bind_from_catalogue(mg)
    _lib(eng, "p1")
    eng.begin_turn()

    zero = GameObject(Card(id="Z", name="Zero", type_line="Creature — Rat", is_creature=True,
                           power=1, toughness=2), owner_id="p2", zone=Zone.BATTLEFIELD)
    zero.controller_id = "p2"
    zero.counters["-1/-1"] = 2  # derived toughness 0
    eng.state.add_to_battlefield(zero)
    eng.recompute_continuous_effects()

    h0 = len(p1.hand)
    eng.rules.destroy(zero)
    eng.resolve_until_stable()
    assert len(p1.hand) == h0 + 1

    healthy = GameObject(Card(id="H", name="Healthy", type_line="Creature — Ox", is_creature=True,
                              power=3, toughness=3), owner_id="p2", zone=Zone.BATTLEFIELD)
    healthy.controller_id = "p2"
    eng.state.add_to_battlefield(healthy)
    h1 = len(p1.hand)
    eng.rules.destroy(healthy)
    eng.resolve_until_stable()
    assert len(p1.hand) == h1  # toughness 3 → no draw


# --- Dusk Urchins ----------------------------------------------------------

DUSK_URCHINS = Card(
    id="DU", name="Dusk Urchins", type_line="Creature — Ouphe", is_creature=True,
    power=1, toughness=3,
    oracle_text="Whenever this creature attacks or blocks, put a -1/-1 counter on it.\n"
                "When this creature dies, draw a card for each -1/-1 counter on it.",
)


def test_dusk_urchins_draws_one_per_minus_counter_on_death():
    eng = _engine()
    p1 = eng.state.players[0]
    du = GameObject(DUSK_URCHINS, owner_id="p1", zone=Zone.BATTLEFIELD)
    du.controller_id = "p1"
    eng.state.add_to_battlefield(du)
    bind_from_catalogue(du)
    _lib(eng, "p1")
    du.counters["-1/-1"] = 3
    eng.begin_turn()

    h0 = len(p1.hand)
    eng.rules.destroy(du)
    eng.resolve_until_stable()
    assert len(p1.hand) == h0 + 3


def test_dusk_urchins_no_counters_no_draw():
    eng = _engine()
    p1 = eng.state.players[0]
    du = GameObject(DUSK_URCHINS, owner_id="p1", zone=Zone.BATTLEFIELD)
    du.controller_id = "p1"
    eng.state.add_to_battlefield(du)
    bind_from_catalogue(du)
    _lib(eng, "p1")
    eng.begin_turn()

    h0 = len(p1.hand)
    eng.rules.destroy(du)
    eng.resolve_until_stable()
    assert len(p1.hand) == h0

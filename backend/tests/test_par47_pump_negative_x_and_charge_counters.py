"""PAR-47 — the charge-counter add/spend cluster's residual gaps.

Three small widenings, all reusing existing engine primitives (no new one
needed — `RulesEngine._substitute_x`/`GameObject.x_paid` already resolve an
``"x"``/``"-x"`` sentinel regardless of whether the announced X paid a mana
cost or a non-mana one like counters removed):

* ``handlers._pump_x`` gains the ``"-x/-x"`` polarity alongside its existing
  ``"+x/+x"`` — Infused Arrows' "remove X charge counters from ~: target
  creature gets -X/-X" spend clause, plus the plain {X}-cost removal family
  (Death Wind, Chill Haunting, Slice from the Shadows, Battle at the
  Bridge's own "You gain X life." tail).
* ``handlers._add_named_counter`` (RULE 122.1's named, non-P/T counters —
  "put a `<kind>` counter on X") now accepts ``COUNT_X`` instead of the
  plain ``COUNT``, so an {X}-cost activated ability's own "put X charge
  counters on ~" (Blast Zone, Ventifact Bottle) is recognized the same way
  the ``+1/+1``/``-1/-1`` counter row already does.
* ``handlers._gain_life`` now accepts ``x`` alongside a literal digit
  ("you gain X life" — Sphinx's Revelation, Death Grasp, Alquist Proft).

Reference: mtg_analyzer/parser/oracle/catalogue/handlers.py.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.effects.core import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.rules.casting_mixin import CastingResolutionMixin
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


# ---------------------------------------------------------------------------
# pump: "-x/-x" polarity
# ---------------------------------------------------------------------------


def test_pump_negative_x_claimed():
    specs = match_clause("target creature gets -x/-x until end of turn")
    assert [s.type for s in specs] == ["pump"]
    p = specs[0].params
    assert p["power"] == "-x" and p["toughness"] == "-x"
    assert p["target_kind"] == "creature"


def test_pump_positive_x_unchanged():
    specs = match_clause("target creature gets +x/+x until end of turn")
    assert specs[0].params["power"] == "x" and specs[0].params["toughness"] == "x"


def test_pump_mixed_sign_stays_unclaimed():
    # No real card splits the sign within one X-pump — the `sign` backreference
    # must keep a nonsensical "+x/-x" fail-closed rather than silently picking one.
    assert match_clause("target creature gets +x/-x until end of turn") is None


def test_pump_negative_x_resolves_to_negative_x_paid_at_runtime():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    src = GameObject(card=Card(id="s", name="Infused Arrows", type_line="Artifact"),
                     owner_id=p1.id, zone=Zone.STACK)
    src.controller_id = p1.id
    src.x_paid = 2
    bear = GameObject(card=Card(id="b", name="Bear", type_line="Creature — Bear",
                                is_creature=True, power=4, toughness=4),
                      owner_id=p1.id, zone=Zone.BATTLEFIELD)
    bear.controller_id = p1.id
    eng.state.add_to_battlefield(bear)
    eff = EffectRegistry.create("pump", {
        "power": "-x", "toughness": "-x", "target_kind": "creature"})
    eff.source = src
    CastingResolutionMixin._substitute_x([eff], 2)
    eff.apply(eng.rules.context, targets=[bear])
    eng.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (2, 2)


@pytest.mark.parametrize("name", ["Death Wind", "Chill Haunting", "Slice from the Shadows"])
def test_negative_x_pump_cards_modeled(name):
    r = parse_oracle(_db().get_card(name))
    assert r.coverage != UNMODELED, r.unclaimed


# ---------------------------------------------------------------------------
# add_named_counter: X-scaled count
# ---------------------------------------------------------------------------


def test_put_x_charge_counters_on_self_parses():
    assert match_clause("put x charge counters on ~") == [
        EffectSpec("add_counters", {"count": "x", "kind": "charge"})
    ]


def test_put_a_charge_counter_on_self_still_fixed_count():
    assert match_clause("put a charge counter on ~") == [
        EffectSpec("add_counters", {"count": 1, "kind": "charge"})
    ]


def test_blast_zone_add_clause_now_modeled_partial():
    # Blast Zone's OWN "put X charge counters" ability is claimed even
    # though the card as a whole stays UNMODELED (its sacrifice-destroy
    # ability is a separate, still-open template).
    card = Card(
        id="Bench Blast Zone", name="Bench Blast Zone", type_line="Land",
        is_land=True,
        oracle_text="{X}{X}, {T}: Put X charge counters on this land.",
    )
    result = parse_oracle(card)
    assert result.modeled is True


def test_x_charge_counters_resolves_to_x_paid_at_runtime():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    src = GameObject(card=Card(id="bz", name="Blast Zone", type_line="Land"),
                     owner_id=p1.id, zone=Zone.BATTLEFIELD)
    src.controller_id = p1.id
    eng.state.add_to_battlefield(src)
    eff = EffectRegistry.create("add_counters", {"count": "x", "kind": "charge"})
    eff.source = src
    CastingResolutionMixin._substitute_x([eff], 4)
    eff.apply(eng.rules.context, targets=[])
    assert src.counters.get("charge", 0) == 4


# ---------------------------------------------------------------------------
# gain_life: "x" amount
# ---------------------------------------------------------------------------


def test_gain_x_life_parses():
    assert match_clause("you gain x life") == [EffectSpec("gain_life", {"amount": "x"})]


def test_gain_fixed_life_unchanged():
    assert match_clause("you gain 3 life") == [EffectSpec("gain_life", {"amount": 3})]


@pytest.mark.parametrize("name", ["Sphinx's Revelation", "Death Grasp"])
def test_gain_x_life_cards_modeled(name):
    r = parse_oracle(_db().get_card(name))
    assert r.coverage != UNMODELED, r.unclaimed

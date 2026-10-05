"""MEC-83 — `effect_amounts` kinds for counters and basic land types.

Two new `AMOUNT_KINDS` so ENG-37's `bind` node can measure them:
  * ``counters`` — ``{"kind": "counters", "counter": "<name>", "of": <ref>}``
    reads `GameObject.counters` on the referent permanent.
  * ``domain`` — ``{"kind": "domain", "of": <player ref>}`` — RULE 702.42a's
    distinct basic land types among that player's lands, deferring to the
    `continuous.count_selector` that already defines it.

Reference: game/effect_amounts.py, parser/oracle/segmenter.py
(`_FOR_EACH_AMOUNTS`, `_FOR_EACH_COUNTER_RE`).
"""

from __future__ import annotations

from mtg_analyzer.game import effect_amounts
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _land(state, name, subtypes, controller="p1"):
    o = GameObject(
        Card(id=name[:8], name=name, is_land=True,
             type_line=f"Land — {' '.join(subtypes)}"),
        owner_id=controller, zone=Zone.BATTLEFIELD,
    )
    o.controller_id = controller
    state.add_to_battlefield(o)
    return o


def _perm(state, name="Rock", controller="p1"):
    o = GameObject(Card(id=name[:8], name=name, type_line="Artifact"),
                   owner_id=controller, zone=Zone.BATTLEFIELD)
    o.controller_id = controller
    state.add_to_battlefield(o)
    return o


# --- engine: counters --------------------------------------------------


def test_counters_kind_reads_the_named_counter_on_the_referent():
    eng = _engine()
    src = _perm(eng.state)
    src.counters["charge"] = 4
    ctx = GameContext(eng.state, eng.rules)
    assert effect_amounts.amount_of(
        {"kind": "counters", "counter": "charge", "of": "source"}, ctx, src
    ) == 4
    # a counter kind it doesn't have → 0, not an error
    assert effect_amounts.amount_of(
        {"kind": "counters", "counter": "verse", "of": "source"}, ctx, src
    ) == 0


def test_counters_kind_reads_plus_one_counters():
    eng = _engine()
    src = _perm(eng.state)
    src.plus_one_counters = 3  # property → counters["+1/+1"] = 3
    ctx = GameContext(eng.state, eng.rules)
    assert effect_amounts.amount_of(
        {"kind": "counters", "counter": "+1/+1", "of": "source"}, ctx, src
    ) == 3


def test_counters_kind_missing_referent_is_zero():
    eng = _engine()
    ctx = GameContext(eng.state, eng.rules)
    assert effect_amounts.amount_of(
        {"kind": "counters", "counter": "charge", "of": "previous_target"}, ctx, None
    ) == 0


# --- engine: domain --------------------------------------------------


def test_domain_counts_distinct_basic_land_types():
    eng = _engine()
    src = _perm(eng.state)
    _land(eng.state, "Forest 1", ["Forest"])
    _land(eng.state, "Forest 2", ["Forest"])  # a second Forest doesn't add
    _land(eng.state, "Island", ["Island"])
    _land(eng.state, "Dual", ["Mountain", "Plains"])  # one land, two types
    _land(eng.state, "Opp Swamp", ["Swamp"], controller="p2")  # not yours
    ctx = GameContext(eng.state, eng.rules)
    # Forest, Island, Mountain, Plains = 4
    assert effect_amounts.amount_of({"kind": "domain", "of": "source"}, ctx, src) == 4


def test_domain_with_no_lands_is_zero():
    eng = _engine()
    src = _perm(eng.state)
    ctx = GameContext(eng.state, eng.rules)
    assert effect_amounts.amount_of({"kind": "domain"}, ctx, src) == 0


# --- parser ----------------------------------------------------------


def test_domain_for_each_becomes_a_bind_node():
    specs = parse_effect_body(
        "create a 3/3 green Beast creature token for each basic land type "
        "among lands you control"
    )
    assert specs is not None and specs[0].type == "bind"
    assert specs[0].params["amount"] == {"kind": "domain"}
    assert specs[0].params["effects"][0]["params"]["count"] == "$n"


def test_named_counter_for_each_becomes_a_bind_node():
    specs = parse_effect_body(
        "you gain 1 life for each verse counter on this enchantment"
    )
    assert specs is not None and specs[0].type == "bind"
    assert specs[0].params["amount"] == {
        "kind": "counters", "counter": "verse", "of": "source",
    }


def test_herd_migration_is_modeled():
    c = CardDatabase(DEFAULT_DB_PATH).get_card("Herd Migration")
    assert c is not None
    assert parse_oracle(c).coverage != UNMODELED


# --- execute: end-to-end through bind --------------------------------


def test_bind_over_domain_scales_the_body():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.parser.oracle.spec import EffectSpec

    eng = _engine()
    src = GameObject(Card(id="hm", name="Herd Migration", type_line="Sorcery"),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    _land(eng.state, "F", ["Forest"])
    _land(eng.state, "I", ["Island"])
    _land(eng.state, "M", ["Mountain"])
    eng.recompute_continuous_effects()

    (node,) = build_effects([EffectSpec("bind", {
        "name": "n", "amount": {"kind": "domain"},
        "effects": [{"type": "gain_life", "params": {"amount": "$n"}}],
    })], src)
    node.apply(GameContext(eng.state, eng.rules))
    assert eng.state.player_by_id("p1").life == 20 + 3

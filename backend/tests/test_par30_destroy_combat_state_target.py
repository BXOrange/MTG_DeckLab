"""PAR-30 — a combat-state ("that's attacking or blocking") tail on the
destroy-colour-adjective target.

`_DESTROY_COLOR_ADJ_RE` gained an optional "…that's attacking or blocking /
attacking / blocking" group → a `creature_filter` boolean;
`combat.matches_object_filter` gained `blocking` / `attacking_or_blocking`
keys (the siblings of the pre-existing `attacking`). Closes Surge of
Righteousness.
"""

from __future__ import annotations

from mtg_analyzer.game.combat import matches_object_filter
from mtg_analyzer.game.effect_binder import build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import legal_targets
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _bf_creature(state, name, colors, pid="p1"):
    o = GameObject(Card(id=name[:6], name=name, type_line="Creature — Bear",
                        is_creature=True, power=2, toughness=2,
                        color_identity=set(colors)),
                   owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    state.add_to_battlefield(o)
    return o


# --- parse -----------------------------------------------------------------


def test_destroy_colour_pair_attacking_or_blocking_parses():
    assert match_clause(
        "destroy target black or red creature that's attacking or blocking"
    ) == [EffectSpec("destroy", {
        "target_kind": "creature", "colors": ["B", "R"],
        "creature_filter": {"attacking_or_blocking": True},
    })]


def test_destroy_single_colour_blocking_parses():
    assert match_clause(
        "destroy target white creature that's blocking"
    ) == [EffectSpec("destroy", {
        "target_kind": "creature", "color": "W",
        "creature_filter": {"blocking": True},
    })]


def test_destroy_attacking_only_parses():
    assert match_clause(
        "destroy target green creature that's attacking"
    ) == [EffectSpec("destroy", {
        "target_kind": "creature", "color": "G",
        "creature_filter": {"attacking": True},
    })]


def test_plain_destroy_colour_still_has_no_filter():
    assert match_clause(
        "destroy target black or red creature"
    ) == [EffectSpec("destroy", {"target_kind": "creature", "colors": ["B", "R"]})]


def test_surge_of_righteousness_modeled():
    c = Card(
        id="sor", name="Surge of Righteousness", type_line="Instant",
        is_instant=True, oracle_text=(
            "Destroy target black or red creature that's attacking or "
            "blocking. You gain 2 life."
        ),
    )
    res = parse_oracle(c)
    assert res.coverage != UNMODELED, res.unclaimed


# --- execute: the filter narrows legal targets --------------------------------


def test_matches_object_filter_blocking_key():
    eng, state = _engine()
    atk = _bf_creature(state, "Atk", {"B"}, "p1")
    blk = _bf_creature(state, "Blk", {"R"}, "p2")
    idle = _bf_creature(state, "Idle", {"B"}, "p2")
    atk.attacking = True
    blk.blocking = atk.instance_id

    assert matches_object_filter(atk, {"attacking_or_blocking": True})
    assert matches_object_filter(blk, {"attacking_or_blocking": True})
    assert not matches_object_filter(idle, {"attacking_or_blocking": True})
    assert matches_object_filter(blk, {"blocking": True})
    assert not matches_object_filter(atk, {"blocking": True})


def test_legal_targets_only_offers_a_combat_creature():
    eng, state = _engine()
    src = GameObject(Card(id="src", name="Src", type_line="Instant", is_instant=True),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    attacker = _bf_creature(state, "Red Attacker", {"R"}, "p2")
    bystander = _bf_creature(state, "Black Bystander", {"B"}, "p2")
    attacker.attacking = True
    eng.recompute_continuous_effects()

    eff = build_effects([EffectSpec("destroy", {
        "target_kind": "creature", "colors": ["B", "R"],
        "creature_filter": {"attacking_or_blocking": True},
    })], src)[0]
    offered = {t["instance_id"] for t in legal_targets(state, "p1", eff.target_spec, src)}

    assert attacker.instance_id in offered
    assert bystander.instance_id not in offered

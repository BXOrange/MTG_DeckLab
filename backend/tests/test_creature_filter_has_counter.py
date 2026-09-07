"""RULE 115/601.2c creature-quality target filter extended to "with a
-1/-1 counter on it" / the kindless "with a counter on it" (Blight Curse
batch — Liliana, Death Wielder's -3; also unlocks Crumbling Ashes).

`_creature_filter_clause` gained two alternatives feeding the shared
`_CREATURE_FILTER_SUFFIX` (so `destroy_creature_filter` /
`damage_creature_filter` / `exile_creature_filter` all pick it up), emitting
`{"has_counter_kind": "-1/-1"}` / `{"has_counter": True}`; `combat.
matches_object_filter` gained the matching keys (reads `GameObject.counters`
directly — counters aren't a continuous effect, so no layer pass needed).
"""

from __future__ import annotations

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


def _creature(state, name, pid="p2", power=2, toughness=2, counters=None):
    o = GameObject(
        Card(id=name[:6], name=name, type_line="Creature — Zombie",
             is_creature=True, power=power, toughness=toughness),
        owner_id=pid, zone=Zone.BATTLEFIELD,
    )
    o.controller_id = pid
    for kind, n in (counters or {}).items():
        o.counters[kind] = n
    state.add_to_battlefield(o)
    return o


def _stack_src(state, pid="p1"):
    src = GameObject(Card(id="src", name="Src", type_line="Instant", is_instant=True),
                     owner_id=pid, zone=Zone.STACK)
    src.controller_id = pid
    return src


# --- parse -----------------------------------------------------------------


def test_destroy_with_minus_counter_filter_parses():
    assert match_clause("destroy target creature with a -1/-1 counter on it") == [
        EffectSpec("destroy", {
            "target_kind": "creature", "creature_filter": {"has_counter_kind": "-1/-1"},
        })
    ]


def test_destroy_with_any_counter_filter_parses():
    assert match_clause("destroy target creature with a counter on it") == [
        EffectSpec("destroy", {
            "target_kind": "creature", "creature_filter": {"has_counter": True},
        })
    ]


def test_damage_with_counter_filter_parses():
    assert match_clause("~ deals 3 damage to target creature with a -1/-1 counter on it") == [
        EffectSpec("damage", {
            "amount": 3, "target_kind": "creature",
            "creature_filter": {"has_counter_kind": "-1/-1"},
        })
    ]


def test_bare_destroy_still_plain():
    assert match_clause("destroy target creature") == [
        EffectSpec("destroy", {"target_kind": "creature"})
    ]


def test_real_cards_modeled():
    for name, text in [
        ("Liliana, Death Wielder",
         "+2: Put a -1/-1 counter on up to one target creature.\n"
         "−3: Destroy target creature with a -1/-1 counter on it.\n"
         "−10: Return all creature cards from your graveyard to the battlefield."),
        ("Crumbling Ashes",
         "At the beginning of your upkeep, destroy target creature with a -1/-1 counter on it."),
    ]:
        c = Card(id=name[:4], name=name,
                 type_line="Legendary Planeswalker — Liliana" if "Liliana" in name else "Enchantment",
                 oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- execute -------------------------------------------------------------------


def test_only_creatures_with_a_minus_counter_are_legal_targets():
    eng, state = _engine()
    src = _stack_src(state)
    marked = _creature(state, "Marked One", counters={"-1/-1": 1})
    plus_only = _creature(state, "Buffed One", counters={"+1/+1": 2})
    bare = _creature(state, "Plain One")
    eng.recompute_continuous_effects()

    eff = build_effects([EffectSpec("destroy", {
        "target_kind": "creature", "creature_filter": {"has_counter_kind": "-1/-1"},
    })], src)[0]
    offered = {t["instance_id"] for t in legal_targets(state, "p1", eff.target_spec, src)}

    assert marked.instance_id in offered
    assert plus_only.instance_id not in offered
    assert bare.instance_id not in offered


def test_kindless_has_counter_matches_any_counter():
    eng, state = _engine()
    src = _stack_src(state)
    plus = _creature(state, "Plus One", counters={"+1/+1": 1})
    bare = _creature(state, "Bare One")
    eng.recompute_continuous_effects()

    eff = build_effects([EffectSpec("destroy", {
        "target_kind": "creature", "creature_filter": {"has_counter": True},
    })], src)[0]
    offered = {t["instance_id"] for t in legal_targets(state, "p1", eff.target_spec, src)}

    assert plus.instance_id in offered
    assert bare.instance_id not in offered

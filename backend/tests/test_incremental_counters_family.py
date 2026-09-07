"""Blight Curse batch — "Put a -1/-1 counter on target creature, two -1/-1
counters on another target creature, and three -1/-1 counters on a third
target creature." (Incremental Blight; the +1/+1 sibling is Incremental
Growth).

Three escalating RULE 115 targets in one clause, each getting a *different*
number of counters, so it can't be one `add_counters` with a target
``count``. `_incremental_counters` emits three `add_counters` `EffectSpec`s;
the spell-resolution loop partitions the chosen targets one per effect. The
2nd/3rd carry `distinct_from_others` for RULE 109.5's "another"/"a third"
(`AddCountersEffect.distinct_from_others` → `TargetSpec`).
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
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


# --- parse -----------------------------------------------------------------


def test_incremental_blight_parses_to_three_escalating_add_counters():
    specs = match_clause(
        "put a -1/-1 counter on target creature, 2 -1/-1 counters on another target "
        "creature, and 3 -1/-1 counters on a third target creature"
    )
    assert specs == [
        EffectSpec("add_counters", {"count": 1, "kind": "-1/-1", "target_kind": "creature"}),
        EffectSpec("add_counters", {
            "count": 2, "kind": "-1/-1", "target_kind": "creature", "distinct_from_others": True,
        }),
        EffectSpec("add_counters", {
            "count": 3, "kind": "-1/-1", "target_kind": "creature", "distinct_from_others": True,
        }),
    ]


def test_incremental_growth_is_the_plus_one_sibling():
    specs = match_clause(
        "put a +1/+1 counter on target creature, 2 +1/+1 counters on another target "
        "creature, and 3 +1/+1 counters on a third target creature"
    )
    assert [s.params["kind"] for s in specs] == ["+1/+1", "+1/+1", "+1/+1"]
    assert [s.params["count"] for s in specs] == [1, 2, 3]


def test_mixed_counter_kinds_fail_closed():
    # No real card mixes kinds across the three clauses; guessing is worse
    # than staying unclaimed.
    assert match_clause(
        "put a +1/+1 counter on target creature, 2 -1/-1 counters on another target "
        "creature, and 3 -1/-1 counters on a third target creature"
    ) is None


def test_real_cards_modeled():
    for name in ("Incremental Blight", "Incremental Growth"):
        text = (
            f"Put a {'-1/-1' if 'Blight' in name else '+1/+1'} counter on target creature, "
            f"two {'-1/-1' if 'Blight' in name else '+1/+1'} counters on another target "
            f"creature, and three {'-1/-1' if 'Blight' in name else '+1/+1'} counters on a "
            f"third target creature."
        )
        c = Card(id=name[:4], name=name, type_line="Sorcery", is_sorcery=True, oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- execute -------------------------------------------------------------------


def test_incremental_blight_partitions_counts_across_three_targets():
    eng, st = _engine()
    p1 = st.players[0]
    victims = []
    for i in range(3):
        o = GameObject(Card(id=f"V{i}", name=f"V{i}", type_line="Creature — Ogre",
                            is_creature=True, power=5, toughness=5),
                       owner_id="p2", zone=Zone.BATTLEFIELD)
        o.controller_id = "p2"
        st.add_to_battlefield(o)
        victims.append(o)

    spell = Card(id="IB", name="Incremental Blight", type_line="Sorcery", is_sorcery=True,
                 mana_cost_string="{3}{B}{B}", converted_mana_cost=5,
                 oracle_text="Put a -1/-1 counter on target creature, two -1/-1 counters on "
                             "another target creature, and three -1/-1 counters on a third "
                             "target creature.")
    obj = GameObject(spell, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    eng.begin_turn()
    st.current_step = "main1"
    p1.mana_pool.add_many({"B": 2, "C": 3})
    eng.cast_spell(p1, obj, targets=[victims[0], victims[1], victims[2]])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()

    assert [v.counters.get("-1/-1", 0) for v in victims] == [1, 2, 3]
    assert [(v.power, v.toughness) for v in victims] == [(4, 4), (3, 3), (2, 2)]

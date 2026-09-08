"""Blight Curse batch C5 wave 4 — Ifnir Deadlands / Archfiend of Ifnir
(hand-authored, `ability_catalogue/entries_017.py`).

* Ifnir Deadlands — sorcery-speed sacrifice ability; the cost's
  ``Sacrifice a Desert`` subtype filter is already parsed by
  `game/costs.parse_activation_cost`; the effect is a plain targeted
  ``add_counters`` (``creature_you_dont_control``).
* Archfiend of Ifnir — "whenever you cycle or discard another card" is two
  events (`CYCLED` + `DISCARD_CARD`), so two triggered abilities; the
  effect is a mass ``add_counters`` with
  ``selector="each_creature_opponents_control"``.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import specs_for
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import legal_targets
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


IFNIR_DEADLANDS = Card(
    id="IFD", name="Ifnir Deadlands", type_line="Land — Desert", is_land=True,
    oracle_text="{T}: Add {C}.\n{T}, Pay 1 life: Add {B}.\n{2}{B}{B}, {T}, Sacrifice a "
                "Desert: Put two -1/-1 counters on target creature an opponent controls. "
                "Activate only as a sorcery.",
)
ARCHFIEND_OF_IFNIR = Card(
    id="AOI", name="Archfiend of Ifnir", type_line="Creature — Demon", is_creature=True,
    power=5, toughness=4, keywords=["Flying", "Cycling"],
    oracle_text="Flying\nWhenever you cycle or discard another card, put a -1/-1 counter "
                "on each creature your opponents control.\nCycling {2}",
)


def test_ifnir_deadlands_sac_ability_authored():
    specs = specs_for(IFNIR_DEADLANDS)
    act = [s for s in specs if s.ability_kind == "activated"]
    assert len(act) == 1
    assert act[0].cost["sorcery_speed_only"] is True


def test_ifnir_deadlands_puts_two_counters_on_an_opponents_creature():
    eng = _engine()
    st = eng.state
    idl = GameObject(IFNIR_DEADLANDS, owner_id="p1", zone=Zone.BATTLEFIELD)
    idl.controller_id = "p1"
    st.add_to_battlefield(idl)
    bind_from_catalogue(idl)

    opp = GameObject(Card(id="O", name="Opp", type_line="Creature — Ogre", is_creature=True,
                          power=4, toughness=4), owner_id="p2", zone=Zone.BATTLEFIELD)
    opp.controller_id = "p2"
    mine = GameObject(Card(id="M", name="Mine", type_line="Creature — Ox", is_creature=True,
                           power=3, toughness=3), owner_id="p1", zone=Zone.BATTLEFIELD)
    mine.controller_id = "p1"
    st.add_to_battlefield(opp)
    st.add_to_battlefield(mine)

    eff = build_effects([EffectSpec("add_counters", {
        "count": 2, "kind": "-1/-1", "target_kind": "creature_you_dont_control",
    })], idl)[0]
    offered = {t["instance_id"] for t in legal_targets(st, "p1", eff.target_spec, source=idl)}
    assert opp.instance_id in offered and mine.instance_id not in offered

    eff.apply(GameContext(st, eng.rules), targets=[opp])
    assert opp.counters.get("-1/-1", 0) == 2


def test_archfiend_two_triggers_one_per_event():
    ta_events = {s.trigger["event"] for s in specs_for(ARCHFIEND_OF_IFNIR)
                 if s.ability_kind == "triggered"}
    assert ta_events == {"CYCLED", "DISCARD_CARD"}


def test_archfiend_discard_puts_a_counter_on_each_opponent_creature():
    eng = _engine()
    st = eng.state
    p1 = st.players[0]
    af = GameObject(ARCHFIEND_OF_IFNIR, owner_id="p1", zone=Zone.BATTLEFIELD)
    af.controller_id = "p1"
    st.add_to_battlefield(af)
    bind_from_catalogue(af)

    opp1 = GameObject(Card(id="O1", name="O1", type_line="Creature — Ogre", is_creature=True,
                           power=3, toughness=3), owner_id="p2", zone=Zone.BATTLEFIELD)
    opp1.controller_id = "p2"
    opp2 = GameObject(Card(id="O2", name="O2", type_line="Creature — Ogre", is_creature=True,
                           power=2, toughness=2), owner_id="p2", zone=Zone.BATTLEFIELD)
    opp2.controller_id = "p2"
    mine = GameObject(Card(id="MC", name="MC", type_line="Creature — Bear", is_creature=True,
                           power=2, toughness=2), owner_id="p1", zone=Zone.BATTLEFIELD)
    mine.controller_id = "p1"
    for o in (opp1, opp2, mine):
        st.add_to_battlefield(o)

    p1.hand.append(GameObject(Card(id="HC", name="HandCard", type_line="Instant", is_instant=True),
                              owner_id="p1", zone=Zone.HAND))
    eng.begin_turn()
    eng.rules.discard_choice(p1, 1)
    for _ in range(3):
        pc = st.pending_choice
        if not pc:
            break
        eng.rules.submit_choice(p1.id, {"instance_id": p1.hand[0].instance_id})
        eng.resolve_until_stable()
    eng.resolve_until_stable()

    assert opp1.counters.get("-1/-1", 0) == 1
    assert opp2.counters.get("-1/-1", 0) == 1
    assert mine.counters.get("-1/-1", 0) == 0


# --- Nesting Grounds (C5 wave 5) — new MoveCountersEffect ------------------

NESTING_GROUNDS = Card(
    id="NGR", name="Nesting Grounds", type_line="Land", is_land=True,
    oracle_text="{T}: Add {C}.\n{1}, {T}: Move a counter from target permanent you control "
                "onto a second target permanent. Activate only as a sorcery.",
)


def test_nesting_grounds_authored_sorcery_speed():
    act = [s for s in specs_for(NESTING_GROUNDS) if s.ability_kind == "activated"]
    assert len(act) == 1 and act[0].cost["sorcery_speed_only"] is True


def test_move_counters_relocates_one_counter_and_updates_pt():
    eng = _engine()
    st = eng.state
    ng = GameObject(NESTING_GROUNDS, owner_id="p1", zone=Zone.BATTLEFIELD)
    ng.controller_id = "p1"
    st.add_to_battlefield(ng)
    bind_from_catalogue(ng)

    src = GameObject(Card(id="S", name="Src", type_line="Creature — Ox", is_creature=True,
                          power=3, toughness=3), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    src.counters["+1/+1"] = 2
    dst = GameObject(Card(id="D", name="Dst", type_line="Creature — Bear", is_creature=True,
                          power=2, toughness=2), owner_id="p1", zone=Zone.BATTLEFIELD)
    dst.controller_id = "p1"
    st.add_to_battlefield(src)
    st.add_to_battlefield(dst)

    eff = build_effects([EffectSpec("move_counters", {})], ng)[0]
    assert [s.kind for s in eff.target_specs] == ["permanent_you_control", "permanent"]
    eff.apply(GameContext(st, eng.rules), targets=[src, dst])
    eng.recompute_continuous_effects()

    assert src.counters.get("+1/+1", 0) == 1 and dst.counters.get("+1/+1", 0) == 1
    assert (src.power, src.toughness) == (4, 4)
    assert (dst.power, dst.toughness) == (3, 3)


def test_move_counters_noop_when_source_has_no_counters():
    eng = _engine()
    st = eng.state
    ng = GameObject(NESTING_GROUNDS, owner_id="p1", zone=Zone.BATTLEFIELD)
    ng.controller_id = "p1"
    st.add_to_battlefield(ng)
    bind_from_catalogue(ng)
    a = GameObject(Card(id="A", name="A", type_line="Creature — Ox", is_creature=True,
                        power=2, toughness=2), owner_id="p1", zone=Zone.BATTLEFIELD)
    a.controller_id = "p1"
    b = GameObject(Card(id="B", name="B", type_line="Creature — Ox", is_creature=True,
                        power=2, toughness=2), owner_id="p1", zone=Zone.BATTLEFIELD)
    b.controller_id = "p1"
    st.add_to_battlefield(a)
    st.add_to_battlefield(b)

    eff = build_effects([EffectSpec("move_counters", {})], ng)[0]
    eff.apply(GameContext(st, eng.rules), targets=[a, b])
    assert not a.counters and not b.counters

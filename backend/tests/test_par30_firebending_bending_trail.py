"""PAR-30 — "Firebending (RULE ~702.189) grants residue": the last open
sub-bullet, the "whenever you waterbend, earthbend, firebend, or airbend"
bending-verb trigger (Avatar Aang).

Engine infrastructure added this batch:

* `EventType.BENT` + `RulesEngine.record_bend` + `GameState.bends_this_turn`
  (cleared each `GameEngine.begin_turn`).
* Fire points: `RulesEngine.earthbend`, the waterbend additional-cast-cost
  payment (RULE 701.67c), `ExileEffect.bend_kind` (airbend), and a second
  `ATTACKS` trigger carrying `RecordBendEffect` on every Firebending
  creature (`effect_binder._kw_firebending`).
* `EffectSpec.condition` key `did_all_bends_this_turn` (Avatar Aang's
  reflexive "then if you've done all four this turn, transform ~").

Avatar Aang itself is hand-authored (`game/ability_catalogue/entries_008.py`)
— a strict singleton whose reflexive transform clause the parser can't
express.
"""

from __future__ import annotations

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game.effects.core import EffectRegistry, GameContext
from mtg_analyzer.game.binding.core import bind_from_catalogue

from tests.support.game import creature, make_engine, obj_on_battlefield


def _events(eng, kind):
    return [e for e in eng.state.event_log if e.type == EventType.BENT and e.get("kind") == kind]


# --- record_bend: the shared primitive --------------------------------

def test_record_bend_fires_event_and_stamps_turn():
    eng = make_engine([creature("F")] * 5, [creature("B")], hand=0)
    p1 = eng.state.player_by_id("p1")

    eng.rules.record_bend(p1, "waterbend", amount=3)

    ev = _events(eng, "waterbend")
    assert len(ev) == 1
    assert ev[0].get("player_id") == "p1"
    assert ev[0].get("amount") == 3
    assert eng.state.bends_this_turn["p1"] == {"waterbend"}


def test_record_bend_rejects_unknown_kind():
    eng = make_engine([creature("F")] * 5, [creature("B")], hand=0)
    p1 = eng.state.player_by_id("p1")
    eng.rules.record_bend(p1, "sandbend")
    assert "p1" not in eng.state.bends_this_turn
    assert not [e for e in eng.state.event_log if e.type == EventType.BENT]


def test_bends_this_turn_cleared_on_begin_turn():
    eng = make_engine([creature("F")] * 40, [creature("B")] * 40, hand=0)
    p1 = eng.state.player_by_id("p1")
    eng.rules.record_bend(p1, "earthbend")
    assert eng.state.bends_this_turn.get("p1") == {"earthbend"}
    eng.run_turn()  # p1's turn ends
    eng.run_turn()  # p2
    assert eng.state.bends_this_turn == {}


# --- each bending primitive fires BENT --------------------------------

def test_earthbend_fires_bent():
    eng = make_engine([creature("F")] * 5, [creature("B")], hand=0)
    land = obj_on_battlefield(
        eng.state, eng,
        Card(id="L", name="Forest", type_line="Basic Land — Forest", is_land=True),
        controller="p1",
    )
    src = obj_on_battlefield(eng.state, eng, creature("Bender"), controller="p1")
    eng.rules.earthbend(land, 2, source=src)

    ev = _events(eng, "earthbend")
    assert len(ev) == 1 and ev[0].get("amount") == 2
    assert eng.state.bends_this_turn["p1"] == {"earthbend"}


def test_airbend_exile_fires_bent():
    eng = make_engine([creature("F")] * 5, [creature("B")], hand=0)
    src = obj_on_battlefield(eng.state, eng, creature("Aang Spell"), controller="p1")
    victim = obj_on_battlefield(eng.state, eng, creature("Victim"), controller="p2")

    effect = EffectRegistry.create("exile", {"target_kind": "creature", "bend_kind": "airbend"})
    effect.source = src
    effect.apply(GameContext(eng.state, eng.rules), targets=[victim])

    assert victim not in eng.state.battlefield
    ev = _events(eng, "airbend")
    assert len(ev) == 1 and ev[0].get("player_id") == "p1"
    assert eng.state.bends_this_turn["p1"] == {"airbend"}


def test_exile_without_bend_kind_does_not_fire_bent():
    eng = make_engine([creature("F")] * 5, [creature("B")], hand=0)
    src = obj_on_battlefield(eng.state, eng, creature("Plain Exile"), controller="p1")
    victim = obj_on_battlefield(eng.state, eng, creature("Victim"), controller="p2")

    effect = EffectRegistry.create("exile", {"target_kind": "creature"})
    effect.source = src
    effect.apply(GameContext(eng.state, eng.rules), targets=[victim])

    assert victim not in eng.state.battlefield
    assert not [e for e in eng.state.event_log if e.type == EventType.BENT]


def test_firebending_attack_fires_bent():
    eng = make_engine([creature("F")] * 5, [creature("B")] * 5, hand=0)
    fb = obj_on_battlefield(
        eng.state, eng,
        creature(
            "Fire Sages", power=2, toughness=2,
            oracle_text="Firebending 1", keywords=["Firebending"],
        ),
        controller="p1",
    )
    bind_from_catalogue(fb)
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    eng.declare_attackers(eng.state.active_player, [fb])
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()

    ev = _events(eng, "firebend")
    assert len(ev) >= 1
    assert eng.state.bends_this_turn.get("p1") == {"firebend"}


# --- Avatar Aang: the trigger ---------------------------------------

def _avatar_aang_card():
    return Card(
        id="tla-aang", name="Avatar Aang // Aang, Master of Elements",
        type_line="Legendary Creature — Human Avatar Ally",
        mana_cost_string="{R}{G}{W}{U}", converted_mana_cost=4,
        is_creature=True, is_legendary=True, power=4, toughness=4,
        oracle_text=(
            "Flying, firebending 2\n"
            "Whenever you waterbend, earthbend, firebend, or airbend, draw a "
            "card. Then if you've done all four this turn, transform Avatar Aang."
        ),
        keywords=["Flying", "Transform", "Firebending"],
        layout="transform",
        back_name="Aang, Master of Elements",
        back_type_line="Legendary Creature — Avatar Ally",
        back_power=6, back_toughness=6,
        back_oracle_text="Flying",
    )


def _aang_on_field(eng):
    aang = obj_on_battlefield(eng.state, eng, _avatar_aang_card(), controller="p1")
    bind_from_catalogue(aang)
    return aang


def test_aang_draws_on_any_bend():
    eng = make_engine([creature("F")] * 10, [creature("B")], hand=0)
    p1 = eng.state.player_by_id("p1")
    aang = _aang_on_field(eng)
    eng.begin_turn()
    before = len(p1.hand)

    eng.rules.record_bend(p1, "waterbend")
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()

    assert len(p1.hand) == before + 1
    assert aang.transformed is False  # only one of four


def test_aang_transforms_after_all_four_bends():
    eng = make_engine([creature("F")] * 10, [creature("B")], hand=0)
    p1 = eng.state.player_by_id("p1")
    aang = _aang_on_field(eng)
    eng.begin_turn()

    for kind in ("waterbend", "earthbend", "firebend", "airbend"):
        eng.rules.record_bend(p1, kind)
        eng.rules.put_triggers_on_stack()
        eng.resolve_until_stable()

    assert eng.state.bends_this_turn["p1"] == {"waterbend", "earthbend", "firebend", "airbend"}
    assert aang.transformed is True
    assert aang.name == "Aang, Master of Elements"


def test_aang_no_transform_when_one_bend_repeated():
    eng = make_engine([creature("F")] * 10, [creature("B")], hand=0)
    p1 = eng.state.player_by_id("p1")
    aang = _aang_on_field(eng)
    eng.begin_turn()

    for _ in range(4):
        eng.rules.record_bend(p1, "airbend")
        eng.rules.put_triggers_on_stack()
        eng.resolve_until_stable()

    assert aang.transformed is False


def test_aang_opponent_bend_does_not_trigger():
    eng = make_engine([creature("F")] * 10, [creature("B")] * 10, hand=0)
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    aang = _aang_on_field(eng)
    eng.begin_turn()
    before = len(p1.hand)

    eng.rules.record_bend(p2, "waterbend")
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()

    assert len(p1.hand) == before
    assert aang.transformed is False


def test_aang_is_hand_authored():
    from mtg_analyzer.game.ability_catalogue import specs_for

    specs = specs_for(_avatar_aang_card())
    assert specs, "Avatar Aang should be hand-authored"
    trg = [s for s in specs if s.ability_kind == "triggered" and s.trigger]
    assert any(s.trigger.get("event") == EventType.BENT for s in trg)

"""PAR-30 — Waterbend (RULE 701.67) residue: the remaining per-card bodies,
hand-authored over new engine primitives.

Primitives added this batch:
* `TemporaryPlayerTrigger` gained ``duration="this_turn"`` (armed active
  immediately, dropped at the next `TURN_BEGIN`) + ``event_player_scope=
  "any"``, and `InstallTemporaryPlayerTriggerEffect` a ``recipient=
  "controller"`` — Ruinous Waterbending's "whenever a creature dies this
  turn, you gain 1 life".
* `look_top_select` gained ``select_optional`` + ``select_filter`` — Water
  Tribe Rallier's "you may reveal a creature card with power 3 or less".
* `no_max_hand_size_rest_of_game` (`GameState.no_max_hand_size_player_ids`)
  — Spirit Water Revival.
* `CopyPermanentEffect` ``referent="previous_each"`` — Foggy Swamp Visions'
  "for each creature card exiled this way, create a token copy of it".
* `ExileEffect`/`TapEffect` gained ``count_selector`` — "exile/tap X target
  …" (Waterbender's Restoration / Crashing Wave).
"""

from __future__ import annotations

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.ability_catalogue import specs_for

from tests.test_game_engine import creature, make_engine, obj_on_battlefield


def _spell(name, tl="Sorcery", mc="{1}{U}{U}", **kw):
    return Card(id=name, name=name, type_line=tl, mana_cost_string=mc,
                converted_mana_cost=3, is_sorcery=True, oracle_text="x", **kw)


def _hand_bound(eng, card):
    p1 = eng.state.player_by_id("p1")
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    p1.hand.append(obj)
    bind_from_catalogue(obj)
    return obj


def _advance_until_step(eng, step, limit=30, active=None):
    for _ in range(limit):
        ran = eng.advance_step()
        if ran and ran[1] == step and (active is None or eng.state.active_player.id == active):
            eng.rules.put_triggers_on_stack()
            eng.resolve_until_stable()
            return
    raise AssertionError(f"never reached {step!r}")


# --- all eight cards are hand-authored ------------------------------

def test_all_residue_cards_registered():
    for name in [
        "Waterbending Lesson", "Water Tribe Rallier", "Ruinous Waterbending",
        "Spirit Water Revival", "Waterbender's Restoration", "Foggy Swamp Visions",
        "Crashing Wave", "Invasion Submersible",
    ]:
        assert specs_for(Card(id=name, name=name, type_line="Sorcery")), name


# --- Ruinous Waterbending -----------------------------------------

def test_ruinous_waterbending_paid_installs_this_turn_death_lifegain():
    eng = make_engine([_spell("Ruinous Waterbending")] * 10,
                      [creature("B")] * 10, hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.player_by_id("p1")
    bear = obj_on_battlefield(eng.state, eng, creature("Bear", power=2, toughness=2),
                              controller="p2")
    o = _hand_bound(eng, _spell("Ruinous Waterbending", tl="Sorcery — Lesson"))
    p1.mana_pool.add("U", 20)
    life0 = p1.life
    eng.cast_spell(p1, o, pay_additional=True)
    eng.resolve_until_stable()
    assert bear not in eng.state.battlefield          # -2/-2 killed it
    assert p1.life - life0 == 1                        # paid → +1 on its death
    assert len(eng.state.temporary_player_triggers) == 1


def test_ruinous_waterbending_unpaid_no_lifegain():
    eng = make_engine([_spell("Ruinous Waterbending")] * 10,
                      [creature("B")] * 10, hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.player_by_id("p1")
    obj_on_battlefield(eng.state, eng, creature("Bear", power=2, toughness=2), controller="p2")
    o = _hand_bound(eng, _spell("Ruinous Waterbending", tl="Sorcery — Lesson"))
    p1.mana_pool.add("U", 20)
    life0 = p1.life
    eng.cast_spell(p1, o)  # decline the optional waterbend
    eng.resolve_until_stable()
    assert p1.life == life0
    assert not eng.state.temporary_player_triggers


def test_ruinous_this_turn_trigger_expires_next_turn():
    eng = make_engine([_spell("Ruinous Waterbending")] * 40,
                      [creature("B")] * 40, hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.player_by_id("p1")
    o = _hand_bound(eng, _spell("Ruinous Waterbending", tl="Sorcery — Lesson"))
    p1.mana_pool.add("U", 20)
    eng.cast_spell(p1, o, pay_additional=True)
    eng.resolve_until_stable()
    assert len(eng.state.temporary_player_triggers) == 1
    eng.run_turn()  # p2's turn begins → the "this turn" trigger drops
    assert not eng.state.temporary_player_triggers


# --- Spirit Water Revival ----------------------------------------

def test_spirit_water_revival_unpaid_draws_two_and_exiles_self():
    eng = make_engine([_spell("Spirit Water Revival")] * 20, [creature("B")] * 20, hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.player_by_id("p1")
    o = _hand_bound(eng, _spell("Spirit Water Revival"))
    p1.mana_pool.add("U", 20)
    h0 = len(p1.hand)
    eng.cast_spell(p1, o)  # decline waterbend {6}
    eng.resolve_until_stable()
    assert len(p1.hand) - h0 == 1          # -1 cast, +2 drawn
    assert o.zone == Zone.EXILE
    assert "p1" not in eng.state.no_max_hand_size_player_ids


def test_spirit_water_revival_paid_wheels_and_grants_no_max_hand():
    eng = make_engine([_spell("Spirit Water Revival")] * 30, [creature("B")] * 30, hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.player_by_id("p1")
    for i in range(3):
        g = GameObject(Card(id=f"g{i}", name=f"G{i}", type_line="Instant"),
                       owner_id="p1", zone=Zone.GRAVEYARD)
        p1.graveyard.append(g)
    o = _hand_bound(eng, _spell("Spirit Water Revival"))
    p1.mana_pool.add("U", 20)
    h0, g0 = len(p1.hand), len(p1.graveyard)
    eng.cast_spell(p1, o, pay_additional=True)
    eng.resolve_until_stable()
    assert len(p1.hand) - h0 == 6          # -1 cast, +7 drawn
    assert len(p1.graveyard) - g0 == -3    # graveyard shuffled into library
    assert o.zone == Zone.EXILE            # "Exile ~" (not to graveyard)
    assert "p1" in eng.state.no_max_hand_size_player_ids


# --- Waterbender's Restoration ---------------------------------

def test_waterbenders_restoration_exiles_x_and_returns_at_next_end_step():
    eng = make_engine([_spell("Waterbender's Restoration", tl="Instant")] * 20,
                      [creature("B")] * 20, hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.player_by_id("p1")
    mine = [obj_on_battlefield(eng.state, eng, creature(f"Bear{i}", power=2, toughness=2),
                               controller="p1") for i in range(2)]
    o = _hand_bound(eng, _spell("Waterbender's Restoration", tl="Instant"))
    p1.mana_pool.add("U", 20)
    eng.cast_spell(p1, o, x=2, targets=[mine[0], mine[1]])
    eng.resolve_until_stable()
    assert all(b.zone == Zone.EXILE for b in mine)
    _advance_until_step(eng, "end")  # "the next end step" — scope "any"
    assert all(b.zone == Zone.BATTLEFIELD for b in mine)
    assert not eng.state.delayed_triggers


# --- Foggy Swamp Visions -------------------------------------

def test_foggy_swamp_visions_copies_each_exiled_and_sacrifices_at_end_step():
    eng = make_engine([_spell("Foggy Swamp Visions")] * 20, [creature("B")] * 20, hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    gy = [GameObject(Card(id=f"gb{i}", name=f"GraveBear{i}", type_line="Creature — Bear",
                          is_creature=True, power=3, toughness=3),
                     owner_id="p2", zone=Zone.GRAVEYARD) for i in range(3)]
    for g in gy:
        p2.graveyard.append(g)
    o = _hand_bound(eng, _spell("Foggy Swamp Visions"))
    p1.mana_pool.add("U", 20)
    eng.cast_spell(p1, o, x=2, targets=[gy[0], gy[1]])
    eng.resolve_until_stable()
    toks = [x for x in eng.state.battlefield if x.name.startswith("GraveBear")]
    assert len(toks) == 2 and all(x.is_token and x.power == 3 for x in toks)
    # "your next end step" — scope "controller", so p1's next end step
    _advance_until_step(eng, "end", limit=40, active="p1")
    assert not [x for x in eng.state.battlefield if x.name.startswith("GraveBear")]


# --- Crashing Wave -----------------------------------------

def test_crashing_wave_taps_x_and_distributes_three_stun():
    eng = make_engine([_spell("Crashing Wave")] * 20, [creature("B")] * 20, hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.player_by_id("p1")
    opp = [obj_on_battlefield(eng.state, eng, creature(f"OppBear{i}", power=2, toughness=2),
                              controller="p2") for i in range(2)]
    o = _hand_bound(eng, _spell("Crashing Wave"))
    p1.mana_pool.add("U", 20)
    eng.cast_spell(p1, o, x=2, targets=[opp[0], opp[1]])
    eng.resolve_until_stable()
    # both tapped, and 3 stun counters split across the two just-tapped
    assert all(b.tapped for b in opp)
    assert sum(b.counters.get("stun", 0) for b in opp) == 3
    assert {b.counters.get("stun", 0) for b in opp} == {1, 2}


# --- Water Tribe Rallier ---------------------------------

def test_water_tribe_rallier_reveals_a_small_creature():
    eng = make_engine([creature("F")] * 3, [creature("B")] * 10, hand=0)
    p1 = eng.state.player_by_id("p1")
    # stack the top 4: a 5/5 (too big), a 2/2 creature (eligible), 2 lands
    top = [
        Card(id="big", name="Big", type_line="Creature — Giant", is_creature=True, power=5, toughness=5),
        Card(id="small", name="Small", type_line="Creature — Mouse", is_creature=True, power=2, toughness=2),
        Card(id="l1", name="L1", type_line="Basic Land — Island", is_land=True),
        Card(id="l2", name="L2", type_line="Basic Land — Island", is_land=True),
    ]
    for c in top:
        p1.library.append(GameObject(c, owner_id="p1", zone=Zone.LIBRARY))
    rallier = obj_on_battlefield(
        eng.state, eng,
        creature("Water Tribe Rallier", power=1, toughness=1),
        controller="p1",
    )
    bind_from_catalogue(rallier)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add("U", 20)
    act = next(a for a in eng.legal_actions(p1)
              if a.get("type") == "activate_ability" and a.get("instance_id") == rallier.instance_id)
    eng.activate_ability(p1, rallier, act.get("ability_index", 0))
    eng.resolve_until_stable()
    # select the eligible small creature
    ch = eng.state.pending_choice
    assert ch and ch["kind"] == "look_top_select"
    # only the 2/2 creature (+ decline) is offered — the 5/5 is filtered out
    labels = {opt["label"] for opt in ch["options"]}
    assert "Small" in labels and "Big" not in labels
    small_id = next(opt["instance_id"] for opt in ch["options"] if opt["label"] == "Small")
    eng.rules.resolve_look_top_select_choice(small_id)
    eng.resolve_until_stable()
    assert any(o.name == "Small" for o in p1.hand)


# --- Invasion Submersible -------------------------------

def test_invasion_submersible_exhaust_becomes_3_3_artifact_creature_once():
    eng = make_engine([creature("F")] * 5, [creature("B")] * 5, hand=0)
    sub = obj_on_battlefield(
        eng.state, eng,
        Card(id="sub", name="Invasion Submersible", type_line="Artifact — Vehicle",
             mana_cost_string="{2}{U}", converted_mana_cost=3, oracle_text="x"),
        controller="p1",
    )
    bind_from_catalogue(sub)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.player_by_id("p1")
    p1.mana_pool.add("U", 20)
    act = next(a for a in eng.legal_actions(p1)
              if a.get("type") == "activate_ability" and a.get("instance_id") == sub.instance_id)
    eng.activate_ability(p1, sub, act.get("ability_index", 0))
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert sub.is_creature
    assert (sub.power, sub.toughness) == (3, 3)   # 0/0 base + three +1/+1
    # once-per-game — no second activation offered
    assert not any(
        a.get("type") == "activate_ability" and a.get("instance_id") == sub.instance_id
        for a in eng.legal_actions(p1)
    )

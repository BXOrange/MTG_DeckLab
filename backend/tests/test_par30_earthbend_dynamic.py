"""PAR-30 — Earthbend dynamic X + the "then untap that land" pronoun tail.

`_earthbend` (RULE 701.66, PAR-29) only handled a literal "earthbend N".
This closes two of its residue items:

- **"earthbend X, where X is [twice] the number of `<count>`"** —
  `_earthbend_x`/`_EARTHBEND_X_RE`. `EarthbendEffect` gained
  `amount_from_count_selector` (a live `continuous.count_selector` read at
  resolution, like `BolsterEffect`) + `amount_multiplier` ("**twice** the
  number of Foods you control" — Bumi's Feast Lecture). Land/artifact
  subtype counts ("forests", "Foods") use a small dedicated map onto
  `lands_you_control_of_type_<x>` / `foods_you_control`; the rest
  ("creatures you control with power N or greater") is built inline.
  Rockalanche, The Boulder Ready to Rumble, Bumi's Feast Lecture.
- **"earthbend N, then untap that land"** (Avatar Kyoshi) — `earthbend` is
  now recognised by `_announces_creature_target` as picking a land (its
  `TargetSpec` is built inside the effect, not surfaced as a param), and a
  new `previous_subject`-only `_TAP_PREVIOUS_SUBJECT_RE` claims "tap/untap
  that land|permanent|artifact|creature" (also unlocking a cluster of
  "pump/attach/counter target creature. Untap that creature." cards).

**"earthbend X, where X is that creature's power"** (PAR-30, v143 —
Beifong's Bounty Hunters, on a "whenever a nonland creature you control
dies" trigger): `_GROUP_SUBJECT_RE` gained an optional `nonland` qualifier
→ `effect_binder._build_group_ok`'s `want_nonland` (checked against the
DIES event's snapshotted `object_types`); `EarthbendEffect.
amount_from_trigger_event="power"` reads the DIES event's RULE 400.7
last-known-power snapshot (`damage_death_mixin` now stamps `power=` on
DIES, mirroring LEAVES_BATTLEFIELD).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _forest(state, pid="p1"):
    o = GameObject(Card(id="F", name="Forest", type_line="Basic Land — Forest", is_land=True),
                   owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    state.add_to_battlefield(o)
    return o


# --- parse ----------------------------------------------------------------


def test_earthbend_x_land_subtype_count_parses():
    assert match_clause("earthbend x, where x is the number of forests you control") == [
        EffectSpec("earthbend", {"amount_from_count_selector": "lands_you_control_of_type_forest"})
    ]


def test_earthbend_x_power_filter_and_twice_multiplier_parse():
    assert match_clause(
        "earthbend x, where x is the number of creatures you control with power 4 or greater"
    ) == [EffectSpec("earthbend", {
        "amount_from_count_selector": "creatures_you_control_with_power_ge_4"})]
    assert match_clause("earthbend x, where x is twice the number of foods you control") == [
        EffectSpec("earthbend", {
            "amount_from_count_selector": "foods_you_control", "amount_multiplier": 2})
    ]


def test_earthbend_x_that_creatures_power_parses():
    assert match_clause("earthbend x, where x is that creature's power") == [
        EffectSpec("earthbend", {"amount_from_trigger_event": "power"})
    ]


def test_earthbend_x_its_bare_power_still_unmodeled():
    # only the explicit "that creature's power" dying-subject shape is claimed
    assert match_clause("earthbend x, where x is its power") is None
    assert match_clause("earthbend x, where x is that creature's toughness") is None


def test_real_cards_modeled():
    for name, tl, text in [
        ("Rockalanche", "Sorcery",
         "Earthbend X, where X is the number of Forests you control."),
        ("Bumi's Feast Lecture", "Sorcery",
         "Create a Food token. Then earthbend X, where X is twice the number "
         "of Foods you control."),
        ("Avatar Kyoshi, Earthbender", "Legendary Creature — Human",
         "At the beginning of combat on your turn, earthbend 8, then untap that land."),
        ("Beifong's Bounty Hunters", "Creature — Human Warrior",
         "Whenever a nonland creature you control dies, earthbend X, where X "
         "is that creature's power."),
    ]:
        c = Card(id=name[:6], name=name, type_line=tl, oracle_text=text,
                 is_creature="Creature" in tl, is_sorcery="Sorcery" in tl,
                 power=3 if "Creature" in tl else None,
                 toughness=3 if "Creature" in tl else None)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- execute ------------------------------------------------------------


def test_beifong_earthbends_by_dying_creatures_power_end_to_end():
    eng, state = _engine()
    land = _forest(state)

    beifong = GameObject(
        Card(id="BEIF", name="Beifong's Bounty Hunters",
             type_line="Creature — Human Warrior", is_creature=True, power=3, toughness=3,
             oracle_text=("Whenever a nonland creature you control dies, earthbend X, "
                          "where X is that creature's power.")),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    beifong.controller_id = "p1"
    state.add_to_battlefield(beifong)
    bind_from_catalogue(beifong)

    victim = GameObject(
        Card(id="VIC", name="Big Ox", type_line="Creature — Ox", is_creature=True,
             power=5, toughness=5),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    victim.controller_id = "p1"
    state.add_to_battlefield(victim)

    eng.rules.destroy(victim)
    eng.resolve_until_stable()
    # one legal "land you control" — auto-resolves the target
    for _ in range(4):
        pc = getattr(state, "pending_choice", None)
        if not pc:
            break
        opts = pc.get("options") or []
        eng.resolve_pending_choice(opts[0]["id"]) if opts else eng.resolve_pending_choice(None)
        eng.resolve_until_stable()

    eng.recompute_continuous_effects()
    assert land.is_creature and land.is_land
    assert land.counters.get("+1/+1") == 5  # the Ox's last-known power


def test_nonland_filter_ignores_a_dying_land():
    eng, state = _engine()
    _forest(state)
    beifong = GameObject(
        Card(id="BEIF2", name="Beifong's Bounty Hunters",
             type_line="Creature — Human Warrior", is_creature=True, power=3, toughness=3,
             oracle_text=("Whenever a nonland creature you control dies, earthbend X, "
                          "where X is that creature's power.")),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    beifong.controller_id = "p1"
    state.add_to_battlefield(beifong)
    bind_from_catalogue(beifong)

    dying_land = _forest(state)  # a plain land dying must NOT fire the trigger
    eng.rules.destroy(dying_land)
    eng.resolve_until_stable()
    assert getattr(state, "pending_choice", None) in (None, {}, [])


def test_earthbend_x_reads_a_live_forest_count():
    eng, state = _engine()
    forests = [_forest(state) for _ in range(3)]
    target = forests[0]

    build_effects([EffectSpec("earthbend", {
        "amount_from_count_selector": "lands_you_control_of_type_forest"})], target)[0].apply(
        eng.rules.context, [target]
    )
    eng.recompute_continuous_effects()
    assert target.is_creature and target.counters.get("+1/+1") == 3


def test_earthbend_x_twice_foods():
    eng, state = _engine()
    land = _forest(state)
    for i in range(2):
        food = GameObject(
            Card(id=f"food{i}", name="Food", type_line="Artifact — Food"),
            owner_id="p1", zone=Zone.BATTLEFIELD,
        )
        food.controller_id = "p1"
        state.add_to_battlefield(food)

    build_effects([EffectSpec("earthbend", {
        "amount_from_count_selector": "foods_you_control", "amount_multiplier": 2})], land)[0].apply(
        eng.rules.context, [land]
    )
    eng.recompute_continuous_effects()
    assert land.counters.get("+1/+1") == 4  # 2 Foods * 2


def test_earthbend_then_untap_that_land_end_to_end():
    eng, state = _engine()
    land = _forest(state)
    land.tapped = True

    effects = build_effects([
        EffectSpec("earthbend", {"amount": 5}),
        EffectSpec("tap", {"previous_subject": True, "untap": True}),
    ], land)
    _apply_effects_partitioned(effects, eng.rules.context, [land], None, source=land)
    eng.recompute_continuous_effects()

    assert land.is_creature and land.counters.get("+1/+1") == 5
    assert land.tapped is False  # the trailing "untap that land" fired

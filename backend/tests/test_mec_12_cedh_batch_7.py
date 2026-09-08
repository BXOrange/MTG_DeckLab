"""MEC-12 continuation, seventh pass (2026-08-11) -- the seven cEDH decks.

The sixth pass had closed every specific, already-diagnosed per-card gap,
leaving only the fourth pass's own broader undesigned subsystems (devotion,
a general "players can't <verb>" family, etc. -- each large enough to be
its own future ticket, not built piecemeal for this one). This pass
re-diagnosed the current residue (baseline re-measured: 462/723 unique
cards across the seven decks) and closed a cluster of narrow, genuinely
reusable gaps instead:

* **The untap-cap family widened past lands-only.** `continuous.
  untap_cap_for_lands` (Winter Orb's own primitive, hardcoded to lands and
  a hardcoded tapped-state check) is now `continuous.active_untap_caps` +
  `matches_untap_cap_filter`: `card_type`/`nonbasic` selector params
  (already-existing `_SELECTOR_KEYS`) widen the scope, and the tapped-state
  gate rides the ordinary RULE 613.6 `active_if` wrapper instead of a
  hardcoded check (Winter Orb's own hand-authored entry updated to carry
  it explicitly). Closes **Static Orb** ("players can't untap more than
  two permanents…") and **Winter Moon** ("…one nonbasic land…") via one
  new parser regex (`_UNTAP_CAP_RE`), both riding the pre-existing
  `_conditional_static_specs`/`static_condition` "as long as ~ is
  untapped" wrapper for Static Orb's own gate for free.
* **Meekstone** -- "Creatures with power N or greater don't untap…" is the
  unattached, group-scoped sibling of `no_untap`'s existing self/attached
  shapes: `affects="all_creatures"` plus the ordinary `min_power` selector
  `group_selector_objects` already applies to every other static family.
  The `no_untap`/`untap_cap` `EffectRegistry` factories had been dropping
  every param but their own hardcoded ones (`params={}`) -- fixed to
  forward `_selectors(p)` like every other static factory does.
* **RULE 115.4 "change the target"** (`ChangeTargetEffect`, built in an
  earlier MEC-12 pass) had no oracle-text handler at all -- only
  Misdirection/Deflecting Swat, both hand-authored. One new handler
  (`_change_target`, `catalogue/handlers.py`) claims "Change the target of
  target spell [or ability] with a single target." generically, closing
  **Deflection**, **Shunt**, **Swerve**, **Willbender** for free alongside
  this pool's own **Bolt Bend**/**Redirect Lightning** (24 cache cards
  print some variant of this phrase).
* **"You control a creature with power N or greater"** as a RULE 613.6
  condition (Bolt Bend's own cost-reduction gate) -- `control_count`'s
  existing `selector`/`min` shape gained an optional `min_power` filter,
  scanning the battlefield directly rather than adding one `count_selector`
  name per possible threshold (58 cache cards print this exact phrase).
* **A spell's own "this spell costs {N} less to cast if/for each…" had
  never reached `static_effect_specs` at all for an instant/sorcery** --
  `segmenter.py`'s `allow_spell_effect` branch only ever tried the
  resolve-time `spell_effect` parse; the static-cost-reduction handlers
  those lines actually need (`_SELF_COST_REDUCTION_IF_RE`/
  `_SELF_COST_REDUCTION_ATTACKING_RE`) only fire from the *permanent* path.
  `continuous.self_cost_reduction_for` already reads a `cost`-layer static
  straight off any object's `static_effects` regardless of zone (proven by
  Ghostfire Slice's own hand-authored entry) -- the only missing piece was
  routing. Closes Bolt Bend's own cost line and, cache-wide, 100+ other
  instant/sorcery cards printing the same template.
* **"Your opponents can't cast spells during your turn."** -- `cast_
  prohibition`'s existing `scope="opponents"` default plus an ordinary
  `active_if={"kind": "your_turn"}` gate already expresses this exactly;
  it just needed a parser row for the trailing-clause phrasing (the
  leading "During your turn, your opponents can't cast spells or activate
  abilities of…" shape was already handled by a different, type-scoped
  row). Closes **Voice of Victory** and, cache-wide, Dragonlord Dromoka/
  Teferi Time Raveler's static half/Jennifer Walters.

Post-batch re-measure: 467/723 unique cards across the seven decks (up
from 462), plus a wider cache-wide effect from every generalized primitive
above. Full backend suite: 3,682 passed (+13 new), 238 skipped, 0
regressions (one pre-existing flaky websocket test, confirmed passing in
isolation).
"""

from __future__ import annotations

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.ability_catalogue import is_registered
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase


def _named(name: str) -> Card:
    return CardDatabase(DB_PATH).get_card(name)


def _engine() -> tuple[GameEngine, GameState]:
    p1 = Player(id="p1", name="Alice", life=20)
    p2 = Player(id="p2", name="Bob", life=20)
    state = GameState(players=[p1, p2])
    engine = GameEngine(state)
    return engine, state


def _bf(state: GameState, card: Card, controller: str = "p1") -> GameObject:
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _to_hand(engine: GameEngine, card: Card, controller: str = "p1") -> GameObject:
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    engine.state.player_by_id(controller).hand.append(obj)
    return obj


def _reach_main(engine: GameEngine, active: str = "p1") -> None:
    engine.begin_turn()
    while engine.state.active_player.id != active:
        engine.begin_turn()
    engine.state.current_step = "main1"
    engine.recompute_continuous_effects()


# ---------------------------------------------------------------------------
# Static Orb / Winter Moon / Meekstone -- the untap-cap/no_untap family
# ---------------------------------------------------------------------------


def _land(name: str, subtype: str = "Forest") -> Card:
    return Card(id=name, name=name, type_line=f"Basic Land — {subtype}", is_land=True)


def test_static_orb_caps_permanents_not_just_lands():
    engine, state = _engine()
    orb = _bf(state, _named("Static Orb"), controller="p2")
    orb.tapped = False
    l1 = _bf(state, _land("SOLand1"), controller="p1")
    l2 = _bf(state, _land("SOLand2", "Island"), controller="p1")
    c1 = _bf(state, Card(id="SOCrea1", name="SOCrea1", type_line="Creature — Bear",
                          is_creature=True, power=2, toughness=2), controller="p1")
    for o in (l1, l2, c1):
        o.tapped = True

    engine._step_untap()

    untapped = sum(1 for o in (l1, l2, c1) if not o.tapped)
    assert untapped == 2  # cap of two permanents, regardless of type


def test_static_orb_inactive_while_tapped():
    engine, state = _engine()
    orb = _bf(state, _named("Static Orb"), controller="p2")
    orb.tapped = True  # "as long as this artifact is untapped" — inactive
    l1 = _bf(state, _land("SOLand3"), controller="p1")
    l1.tapped = True

    engine._step_untap()

    assert l1.tapped is False


def test_winter_moon_caps_nonbasic_lands_only():
    engine, state = _engine()
    _bf(state, _named("Winter Moon"), controller="p2")
    nonbasic1 = _bf(state, Card(id="WMNonbasic1", name="WMNonbasic1",
                                 type_line="Land", is_land=True), controller="p1")
    nonbasic2 = _bf(state, Card(id="WMNonbasic2", name="WMNonbasic2",
                                 type_line="Land", is_land=True), controller="p1")
    basic = _bf(state, _land("WMBasic1"), controller="p1")
    for o in (nonbasic1, nonbasic2, basic):
        o.tapped = True

    engine._step_untap()

    untapped_nonbasic = sum(1 for o in (nonbasic1, nonbasic2) if not o.tapped)
    assert untapped_nonbasic == 1
    assert basic.tapped is False  # unaffected — the cap is nonbasic-only


def test_meekstone_stops_high_power_creatures_untapping():
    engine, state = _engine()
    _bf(state, _named("Meekstone"), controller="p2")
    big = _bf(state, Card(id="MSBig", name="MSBig", type_line="Creature — Giant",
                           is_creature=True, power=3, toughness=3), controller="p1")
    small = _bf(state, Card(id="MSSmall", name="MSSmall", type_line="Creature — Sprite",
                             is_creature=True, power=2, toughness=2), controller="p1")
    big.tapped = True
    small.tapped = True
    engine.recompute_continuous_effects()

    engine._step_untap()

    assert big.tapped is True  # power >= 3 — held down
    assert small.tapped is False  # power < 3 — untaps normally


def test_static_orb_winter_moon_meekstone_are_modeled():
    for name in ("Static Orb", "Winter Moon", "Meekstone"):
        assert parse_oracle(_named(name)).modeled, name


# ---------------------------------------------------------------------------
# RULE 115.4 "change the target" -- generic oracle-text handler
# ---------------------------------------------------------------------------


def test_change_target_generic_handler_covers_plain_and_ability_variants():
    for name in ("Deflection", "Shunt", "Swerve", "Willbender"):
        assert parse_oracle(_named(name)).modeled, name


def test_bolt_bend_is_modeled():
    assert parse_oracle(_named("Bolt Bend")).modeled


# ---------------------------------------------------------------------------
# "You control a creature with power N or greater" -- control_count min_power
# ---------------------------------------------------------------------------


def test_bolt_bend_cost_reduction_condition_execute():
    from mtg_analyzer.game import continuous

    engine, state = _engine()
    p1 = state.player_by_id("p1")
    spell = _to_hand(engine, _named("Bolt Bend"), controller="p1")

    net, _ = continuous.self_cost_reduction_for(spell, state)
    assert net == 0  # no big creature yet — condition false

    big = _bf(state, Card(id="BBBig", name="BBBig", type_line="Creature — Giant",
                           is_creature=True, power=4, toughness=4), controller="p1")
    engine.recompute_continuous_effects()
    net, _ = continuous.self_cost_reduction_for(spell, state)
    assert net == 3  # power 4 creature present — {3} less


# ---------------------------------------------------------------------------
# "Your opponents can't cast spells during your turn." -- cast_prohibition
# ---------------------------------------------------------------------------


def test_voice_of_victory_is_modeled():
    assert parse_oracle(_named("Voice of Victory")).modeled


def test_opponents_cant_cast_prohibition_execute():
    from mtg_analyzer.game import continuous

    engine, state = _engine()
    _bf(state, _named("Voice of Victory"), controller="p1")
    p2 = state.player_by_id("p2")
    bolt = Card(id="Shock", name="Shock", type_line="Instant",
                mana_cost_string="{R}", converted_mana_cost=1, is_instant=True)

    state.active_player_index = 0  # p1's turn
    assert continuous.cast_prohibited(state, p2, bolt) is True

    state.active_player_index = 1  # p2's own turn — unrestricted
    assert continuous.cast_prohibited(state, p2, bolt) is False

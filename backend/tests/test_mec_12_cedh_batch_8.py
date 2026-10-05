"""MEC-12 continuation, eighth pass (2026-08-11) -- the seven cEDH decks.

Continuation of the seventh pass (see `Done_Backend.md`'s matching entry).
Baseline re-measured at the start: 467/723 unique cards across the seven
decks. This pass closed a small, well-scoped cluster rather than the two
"broader gap" primitives the seventh pass had explicitly deferred
(Grafdigger's Cage/Weathered Runestone's zone-cast-restriction pair --
still open, still needing two genuinely new primitives):

- **Back to Basics** -- "Nonbasic lands don't untap during their
  controllers' untap steps." is `no_untap`'s unconditional, unlimited-count
  sibling to the seventh pass's own `_UNTAP_CAP_RE` (Winter Moon's "…can't
  untap more than one nonbasic land…", a cap that still lets the first one
  through): `affects="all_lands"` + the ordinary `nonbasic` selector
  `group_selector_objects` already applies elsewhere -- no new engine code,
  one new parser row (`_NO_UNTAP_NONBASIC_LANDS_RE`).
- **Auriok Salvagers** -- "{1}{W}: return target artifact card **with mana
  value 1 or less** from your graveyard to your hand." needed `Return
  FromGraveyardEffect`/its `_RETURN_FROM_GRAVEYARD_RE` handler to accept the
  same `TargetSpec.max_mana_value` offer-time cap `destroy_mv` already
  uses -- previously dropped entirely (no field on the effect, no capture
  group in the regex, no filter in `targeting.py`'s graveyard-target-kind
  branch). Cache-wide this same widening reaches 102 real cards printing
  "return target `<type>` card with mana value N or less from `<scope>`
  graveyard to `<dest>`" (Sun Titan, Unearth, Teshar Ancestor's Apostle,
  Ral Zarek among them), not just this pool's own card.
- **Assassin's Trophy** -- "Destroy target permanent an opponent controls.
  Its controller may search their library for a basic land card, put it
  onto the battlefield, then shuffle." needed two independent gaps closed:
  (1) `targeting.py`'s `TARGET` macro had "target creature an opponent
  controls" (`creature_you_dont_control`) but no equivalent unscoped-by-
  type "target permanent an opponent controls" row at all -- new
  `permanent_you_dont_control` kind, both in `targeting.legal_targets` and
  `subgrammars._TARGET_ROWS`, plus widening the plain `_destroy` handler's
  own `kind not in (...)` whitelist to accept it (it had been hardcoded to
  just `"creature"`/`"permanent"`, silently rejecting a real match `resolve_
  target_kind` had already produced). Reaches 12 cache-wide cards on its
  own (Teferi Hero of Dominaria, Kiora the Crashing Wave, Elspeth Conquers
  Death among them). (2) The second sentence's actor is "its controller"
  (whoever just lost the destroyed permanent), not the caster --
  `SearchLibraryEffect` gained the same `player="previous_target_
  controller"` sentinel `PayCostThenEffect`'s own `payer` param already
  uses for Chain of Vapor (`GameContext.previous_targets`), plus a new
  parser row (`_DESTROY_CONTROLLER_SEARCH_BASIC_LAND_RE`) recognizing the
  fixed trailing sentence -- also closing Geomancer's Gambit and Ghost
  Quarter (a hand-authored card whose activated ability's second clause
  had been left undocumented-partial until now) for free.

New tests below (10 execute/parse tests). Full backend suite: 3,692
passed, 238 skipped, 0 regressions (one pre-existing flaky websocket test,
confirmed passing in isolation both before and after this batch).
`PARSER_VERSION` bumped 71 -> 72.
"""

from __future__ import annotations

from mtg_analyzer.config import DB_PATH
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


def _land(name: str, subtype: str = "Forest") -> Card:
    return Card(id=name, name=name, type_line=f"Basic Land — {subtype}", is_land=True)


# ---------------------------------------------------------------------------
# Back to Basics -- no_untap, unattached, unlimited, nonbasic-only
# ---------------------------------------------------------------------------


def test_back_to_basics_is_modeled():
    assert parse_oracle(_named("Back to Basics")).modeled


def test_back_to_basics_blocks_every_nonbasic_land():
    engine, state = _engine()
    _bf(state, _named("Back to Basics"), controller="p2")
    nonbasic1 = _bf(state, Card(id="BTBNonbasic1", name="BTBNonbasic1",
                                 type_line="Land", is_land=True), controller="p1")
    nonbasic2 = _bf(state, Card(id="BTBNonbasic2", name="BTBNonbasic2",
                                 type_line="Land", is_land=True), controller="p1")
    basic = _bf(state, _land("BTBBasic1"), controller="p1")
    for o in (nonbasic1, nonbasic2, basic):
        o.tapped = True

    engine._step_untap()

    assert nonbasic1.tapped is True and nonbasic2.tapped is True  # no cap — both stay down
    assert basic.tapped is False


# ---------------------------------------------------------------------------
# Auriok Salvagers -- return_from_graveyard's max_mana_value cap
# ---------------------------------------------------------------------------


def test_auriok_salvagers_is_modeled():
    assert parse_oracle(_named("Auriok Salvagers")).modeled


def test_auriok_salvagers_activated_ability_offers_only_cheap_artifacts():
    from mtg_analyzer.game import targeting
    from mtg_analyzer.models.game.game_object import Zone as _Zone

    engine, state = _engine()
    salvagers = _bf(state, _named("Auriok Salvagers"), controller="p1")
    p1 = state.player_by_id("p1")
    cheap = GameObject(
        Card(id="CheapArt", name="CheapArt", type_line="Artifact",
             mana_cost_string="{1}", converted_mana_cost=1),
        owner_id="p1", zone=_Zone.GRAVEYARD,
    )
    pricey = GameObject(
        Card(id="PriceyArt", name="PriceyArt", type_line="Artifact",
             mana_cost_string="{3}", converted_mana_cost=3),
        owner_id="p1", zone=_Zone.GRAVEYARD,
    )
    p1.graveyard.extend([cheap, pricey])

    ability = salvagers.activated_abilities[0]
    spec = ability.effects[0].target_spec
    assert spec is not None and spec.max_mana_value == 1
    targets = targeting.legal_targets(state, "p1", spec, source=salvagers)
    names = {t["name"] for t in targets}
    assert "CheapArt" in names
    assert "PriceyArt" not in names


# ---------------------------------------------------------------------------
# Assassin's Trophy -- permanent_you_dont_control target + controller-redirected search
# ---------------------------------------------------------------------------


def test_assassins_trophy_is_modeled():
    assert parse_oracle(_named("Assassin's Trophy")).modeled


def test_geomancers_gambit_and_ghost_quarter_are_modeled():
    assert parse_oracle(_named("Geomancer's Gambit")).modeled
    assert parse_oracle(_named("Ghost Quarter")).modeled


def test_assassins_trophy_destroys_and_offers_search_to_the_victims_controller():
    engine, state = _engine()
    p1 = state.player_by_id("p1")
    p2 = state.player_by_id("p2")
    spell = _to_hand(engine, _named("Assassin's Trophy"), controller="p1")
    p1.mana_pool.add_many({"B": 1, "G": 1})
    victim = _bf(state, Card(id="VictimPerm", name="VictimPerm", type_line="Artifact"),
                 controller="p2")
    basic = GameObject(_land("AssassinBasic"), owner_id="p2", zone=Zone.LIBRARY)
    p2.library.append(basic)
    _reach_main(engine)

    engine.cast_spell(p1, spell, targets=[victim])
    engine.resolve_until_stable()

    assert not any(o.instance_id == victim.instance_id for o in state.battlefield)
    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "search"
    assert state.pending_choice["player_id"] == "p2"  # the victim's controller, not the caster

    engine.rules.resolve_choice(basic.instance_id)
    assert state.pending_choice is None


def test_ghost_quarter_destroys_and_offers_search_to_land_controller():
    engine, state = _engine()
    p1 = state.player_by_id("p1")
    p2 = state.player_by_id("p2")
    ghost_quarter = _bf(state, _named("Ghost Quarter"), controller="p1")
    victim = _bf(state, _land("VictimLand", "Island"), controller="p2")
    basic = GameObject(_land("GhostQuarterBasic"), owner_id="p2", zone=Zone.LIBRARY)
    p2.library.append(basic)
    _reach_main(engine)

    engine.activate_ability(p1, ghost_quarter, 0, targets=[victim])
    engine.resolve_until_stable()

    assert victim not in state.battlefield
    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "search"
    assert state.pending_choice["player_id"] == "p2"
    assert any(option["instance_id"] == basic.instance_id for option in state.pending_choice["options"])

    engine.rules.resolve_choice(basic.instance_id)
    assert basic in state.battlefield
    assert state.pending_choice is None
    assert any(
        o.instance_id == basic.instance_id and o.controller_id == "p2" for o in state.battlefield
    )


def test_assassins_trophy_targets_only_opponents_permanents():
    from mtg_analyzer.game import targeting

    engine, state = _engine()
    trophy = _bf(state, _named("Assassin's Trophy"), controller="p1")
    from mtg_analyzer.game.targeting import TargetSpec

    own = _bf(state, Card(id="OwnPerm", name="OwnPerm", type_line="Artifact"), controller="p1")
    theirs = _bf(state, Card(id="TheirPerm", name="TheirPerm", type_line="Artifact"), controller="p2")

    spec = TargetSpec(kind="permanent_you_dont_control")
    targets = targeting.legal_targets(state, "p1", spec, source=trophy)
    names = {t["name"] for t in targets}
    assert "TheirPerm" in names
    assert "OwnPerm" not in names

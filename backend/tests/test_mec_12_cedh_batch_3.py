"""MEC-12 continuation, third pass (2026-08-10) — the seven cEDH decks.

Re-measured baseline before this pass: 764 unique cards across the seven
decks, 430 covered / 334 uncovered (`Ojer cEDH` 48/125, `cEDH Rocco` 70/98,
`[cEDH] Glarb Bloomsday` 71/100, `cEDH staples` 160/215, `cEDH staples 2`
377/607, `cEDH M-K` 73/97, `cEDH Kinnan` 69/100 — the per-deck totals drift
run to run since these are live, user-editable saved decks; re-measure
rather than trusting these numbers as they age).

This pass closed the highest deck-frequency remainder:

* **Mana-ability coverage-classification fix** (`parser/oracle/segmenter.py`
  `_COLORS_AMONG_PERMANENTS_MANA_RE`) — Bloom Tender's "For each color among
  permanents you control, add one mana of that color." was already fully
  *behaviorally* modeled (`game/mana_abilities.py`'s own
  `_COLORS_AMONG_PERMANENTS_RE`, built for ENG-27) but the front-end's
  mana-ability claim check only recognized a line starting with the literal
  word "add" — this phrasing doesn't, so the card scored UNMODELED despite
  playing correctly. A gate-classification fix, not a behavior change.
* **RULE 118.7/601.2f cost-reduction generalization**
  (`game/continuous.py`/`game/effects.py`/`parser/oracle/catalogue/
  static_handlers.py`): the engine already had `cost_reduction_for`/
  `self_cost_reduction_for`/`activation_cost_reduction_for` (Delve, Affinity,
  the Medallion cycle's own colour param, Power Artifact, Sam Loyal
  Attendant) — this pass added the two group scopes and one tax direction
  nothing had used yet: `affects="opponents_spells"` (Grand Arbiter
  Augustin IV's tax half), a `card_type` group scope on
  `scope="activation"` (Training Grounds's "creatures you control", next to
  the existing `subtype` scope), and — the actual gap — **oracle-text
  recognition** of the colour-scoped cast-cost filter
  (`_SPELL_COST_TAX_COLOR_RE`) and the opponents-scoped tax
  (`_SPELL_COST_TAX_OPPONENTS_RE`)/activation group scope
  (`_ACTIVATION_COST_REDUCTION_TYPE_RE`), none of which any parser handler
  had ever claimed.
* **Otawara, Soaring City** hand-authored (`game/ability_catalogue.py`),
  mirroring Eiganjo/Boseiju's existing Channel + per-legendary-creature
  `ActivationCost.dynamic_reduction` shape exactly — the only new piece is
  `targeting.py`'s `artifact_creature_enchantment_or_planeswalker` target
  kind, its own printed four-permanent-type union.
* **"[You may c]ast spells this turn as though they had flash."** parser
  recognition (Emergence Zone) — the effect already shipped as
  `GrantFlashUntilEndOfTurnEffect` (Borne Upon a Wind, hand-authored only).
* **Mindbreak Trap's free-cast condition** — RULE 601.2f's
  `free_cast_condition` family (previously reachable only via hand-authored
  cards, per MEC-15) gained a board-*count* condition kind,
  `opponent_spells_cast_this_turn_at_least`, alongside the existing boolean
  ones. Mindbreak Trap's own second clause ("exile any number of target
  spells", RULE 601.2c's genuinely unbuilt *unbounded* target count) is
  still open — this is real, tested, reusable infrastructure regardless.
* **Smothering Tithe** hand-authored, the `TaxedDrawEffect` family's first
  member whose trigger isn't `SPELL_CAST`: `effect_binder.
  _GROUP_CONTROLLER_EVENT_KEYS` gained a `"DRAW": "player_id"` row (`RulesEngine.
  draw` already fired the event with the right shape), and the "if you
  don't" branch is `effects.PayCostThenEffect`'s general RULE 118.3 shape
  (`payer="event_player"`, `else_effects=[create_token]`) rather than
  `TaxedDrawEffect` itself, since the payoff is a Treasure, not a draw.
"""

from __future__ import annotations

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import continuous
from mtg_analyzer.game.ability_catalogue import is_registered
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase


def _named(name):
    return CardDatabase(DB_PATH).get_card(name)


def _engine(*player_ids):
    players = [Player(id=pid, life=20) for pid in player_ids] or [
        Player(id="p1", life=20), Player(id="p2", life=20),
    ]
    state = GameState(players=players)
    return GameEngine(state), state


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _land(name, subtype="Forest", text="{T}: Add {G}."):
    return Card(
        id=name, name=name, type_line=f"Basic Land — {subtype}", is_land=True,
        oracle_text=text,
    )


def _give_library(state, player_id, count=3):
    player = state.player_by_id(player_id)
    for i in range(count):
        player.library.append(
            GameObject(_land(f"Filler {i}"), owner_id=player_id, zone=Zone.LIBRARY)
        )


# ---------------------------------------------------------------------------
# Bloom Tender — mana-ability coverage-classification fix
# ---------------------------------------------------------------------------


def test_bloom_tender_is_modeled_and_produces_mana_per_color_on_board():
    card = _named("Bloom Tender")
    result = parse_oracle(card)
    assert result.modeled

    engine, state = _engine("p1")
    forest = _bf(state, _land("Forest"))
    bloom_tender = _bf(state, card)
    engine.recompute_continuous_effects()

    engine.tap_for_mana(state.player_by_id("p1"), bloom_tender)
    pool = state.player_by_id("p1").mana_pool.pool
    # Only green permanents on board (Forest, Bloom Tender itself) -> {G}.
    assert pool.get("G", 0) == 1
    assert forest.tapped is False  # Bloom Tender's own {T}, not the Forest's


# ---------------------------------------------------------------------------
# Cost reduction: colour-scoped tax, opponents-scoped tax, activation
# card-type group scope
# ---------------------------------------------------------------------------


def test_grand_arbiter_reduces_own_white_and_blue_spells_and_taxes_opponents():
    engine, state = _engine("p1", "p2")
    _bf(state, _named("Grand Arbiter Augustin IV"))
    engine.recompute_continuous_effects()

    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    white_spell = GameObject(
        Card(id="Test White", name="Test White", type_line="Instant",
             mana_cost_string="{1}{W}", color_identity={"W"}),
        owner_id="p1", zone=Zone.HAND,
    )
    reduction, _ = continuous.cost_reduction_for(state, p1, white_spell)
    assert reduction == 1

    opponent_spell = GameObject(
        Card(id="Test Opp", name="Test Opp", type_line="Instant",
             mana_cost_string="{1}", color_identity=set()),
        owner_id="p2", zone=Zone.HAND,
    )
    tax, _ = continuous.cost_reduction_for(state, p2, opponent_spell)
    assert tax == -1  # "cost {1} more" — a negative reduction


def test_training_grounds_reduces_creature_activated_abilities_with_floor():
    engine, state = _engine("p1")
    _bf(state, _named("Training Grounds"))
    bear = _bf(state, Card(
        id="Bear", name="Bear", type_line="Creature — Bear",
        is_creature=True, power=2, toughness=2,
    ))
    engine.recompute_continuous_effects()

    net, floor = continuous.activation_cost_reduction_for(state, bear)
    assert net == 2
    assert floor == 1


# ---------------------------------------------------------------------------
# Otawara, Soaring City — hand-authored Channel + dynamic_reduction
# ---------------------------------------------------------------------------


def test_otawara_is_registered_and_bounces_with_legendary_discount():
    assert is_registered("Otawara, Soaring City")

    engine, state = _engine("p1", "p2")
    # Channel (RULE 702.29) is a hand-zone `discard_self` ability — Otawara
    # is activated from hand, not the battlefield.
    otawara = GameObject(_named("Otawara, Soaring City"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(otawara)
    p1 = state.player_by_id("p1")
    p1.add_to_zone(otawara, Zone.HAND)
    # Two legendary creatures you control -> {1} less twice off {3}{U}.
    _bf(state, Card(
        id="Legend One", name="Legend One", type_line="Legendary Creature — Human",
        is_creature=True, power=1, toughness=1,
    ))
    _bf(state, Card(
        id="Legend Two", name="Legend Two", type_line="Legendary Creature — Human",
        is_creature=True, power=1, toughness=1,
    ))
    engine.recompute_continuous_effects()

    target = _bf(state, Card(
        id="Target Art", name="Target Art", type_line="Artifact",
    ), controller="p2")

    p1.mana_pool.add("U", 2)  # {3}{U} - {2} (two legends) = {1}{U}
    ability = otawara.activated_abilities[0]
    assert engine.can_activate(p1, otawara, ability)
    engine.activate_ability(p1, otawara, 0, targets=[target])
    engine.resolve_until_stable()

    assert target not in state.battlefield
    p2 = state.player_by_id("p2")
    assert any(o.name == "Target Art" for o in p2.hand)


# ---------------------------------------------------------------------------
# Emergence Zone — "cast spells this turn as though they had flash"
# ---------------------------------------------------------------------------


def test_emergence_zone_is_modeled_and_grants_flash_this_turn():
    result = parse_oracle(_named("Emergence Zone"))
    assert result.modeled

    engine, state = _engine("p1")
    zone = _bf(state, _named("Emergence Zone"))
    engine.recompute_continuous_effects()
    p1 = state.player_by_id("p1")
    p1.mana_pool.add("C", 1)

    ability = zone.activated_abilities[0]
    assert engine.can_activate(p1, zone, ability)
    engine.activate_ability(p1, zone, 0)
    engine.resolve_until_stable()
    # A "you may" grant offers a choice; answer "yes" if one is pending.
    if state.pending_choice is not None:
        engine.rules.resolve_pay_cost_then_choice("pay")
        engine.resolve_until_stable()

    assert state.temp_flash_until_turn.get("p1") == state.turn_number


# ---------------------------------------------------------------------------
# Mindbreak Trap — free_cast_condition's new count-threshold kind
# ---------------------------------------------------------------------------


def test_mindbreak_trap_free_cast_condition_gates_on_opponent_spell_count():
    from mtg_analyzer.game.condition_query import free_cast_condition_holds

    engine, state = _engine("p1", "p2")
    trap = GameObject(_named("Mindbreak Trap"), owner_id="p1", zone=Zone.HAND)
    condition = {"opponent_spells_cast_this_turn_at_least": 3}

    state.spells_cast_this_turn["p2"] = 2
    assert not free_cast_condition_holds(condition, trap, state)

    state.spells_cast_this_turn["p2"] = 3
    assert free_cast_condition_holds(condition, trap, state)


# ---------------------------------------------------------------------------
# Smothering Tithe — DRAW-triggered PayCostThenEffect, not TaxedDrawEffect
# ---------------------------------------------------------------------------


def test_smothering_tithe_creates_treasure_when_opponent_declines_to_pay():
    assert is_registered("Smothering Tithe")

    engine, state = _engine("p1", "p2")
    _give_library(state, "p2")
    _bf(state, _named("Smothering Tithe"))
    engine.recompute_continuous_effects()

    p2 = state.player_by_id("p2")
    engine.rules.draw(p2, 1)
    engine.resolve_until_stable()
    assert state.pending_choice is None  # p2 can't pay {2} -> auto-declines
    assert sum(1 for o in state.battlefield if o.name == "Treasure") == 1
    assert next(o for o in state.battlefield if o.name == "Treasure").controller_id == "p1"


def test_smothering_tithe_offers_a_choice_and_no_treasure_when_paid():
    engine, state = _engine("p1", "p2")
    _give_library(state, "p2")
    _bf(state, _named("Smothering Tithe"))
    engine.recompute_continuous_effects()

    p2 = state.player_by_id("p2")
    p2.mana_pool.add("C", 2)
    engine.rules.draw(p2, 1)
    engine.resolve_until_stable()
    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "pay_cost_then"

    engine.rules.resolve_pay_cost_then_choice("pay")
    engine.resolve_until_stable()

    assert p2.mana_pool.pool.get("C", 0) == 0
    assert not any(o.name == "Treasure" for o in state.battlefield)

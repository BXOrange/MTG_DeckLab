"""BUG-54 -- cast-time "exile N cards from your graveyard" costs are the caster's pick (RULE 601.2h / 702.138).

Covers both shapes: an additional cast cost (Cobbled Lancer) and Escape's own exile cost (a granted Escape via
Underworld Breach). The legal action offers the pool as ``graveyard_exile_cost``; ``cast_spell`` takes the
``graveyard_exile_choices`` answer, validates it before paying anything, and a call without picks keeps the
non-interactive first-match fallback.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.game_session import GameSession
from tests.test_cedh_cube_keyword_mechanics import _card, _catalogue_obj, _engine
from tests.test_par41_exile_graveyard_cast_cost import _setup as _lancer_setup

ESCAPE_EXILE_COUNT = 3  # Underworld Breach: "exile three other cards from your graveyard"


def _bear(name):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True, power=2, toughness=2)


def _gy_ids(player):
    return [o.instance_id for o in player.graveyard]


def _lancer(n=3):
    eng, p1, lancer = _lancer_setup([_bear(f"Dead{i}") for i in range(n)])
    return eng, p1, lancer, list(p1.graveyard)


def _escape(n=4):
    engine, state, p1, _ = _engine()
    state.add_to_battlefield(_catalogue_obj("Underworld Breach"))
    bolt = GameObject(_card("Bolt", "Instant", "{R}", 1), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.add_to_zone(bolt, Zone.GRAVEYARD)
    fuel = []
    for i in range(n):
        o = GameObject(_card(f"Fuel{i}", "Instant", "{R}", 1), owner_id="p1", zone=Zone.GRAVEYARD)
        p1.add_to_zone(o, Zone.GRAVEYARD)
        fuel.append(o)
    p1.mana_pool.add("R", 2)
    return engine, p1, bolt, fuel


# --- additional cast cost ------------------------------------------------------------------------------------------

def test_additional_cost_pick_is_honoured():
    eng, p1, lancer, gy = _lancer()
    eng.cast_spell(p1, lancer, graveyard_exile_choices=[gy[2].instance_id])
    assert gy[2].zone == Zone.EXILE
    assert gy[0].zone == Zone.GRAVEYARD and gy[1].zone == Zone.GRAVEYARD


@pytest.mark.parametrize("bad", ["too_many", "empty", "foreign", "duplicate"])
def test_additional_cost_invalid_picks_rejected_without_state_change(bad):
    eng, p1, lancer, gy = _lancer()
    land = GameObject(Card(id="isl", name="Island", type_line="Basic Land — Island", is_land=True),
                      owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(land)  # in the graveyard but not a creature card
    picks = {"too_many": [gy[0].instance_id, gy[1].instance_id], "empty": [],
             "foreign": [land.instance_id], "duplicate": [gy[0].instance_id] * 2}[bad]
    before, mana = _gy_ids(p1), p1.mana_pool.total()
    with pytest.raises(ValueError):
        eng.cast_spell(p1, lancer, graveyard_exile_choices=picks)
    assert _gy_ids(p1) == before and not eng.state.stack and lancer.zone == Zone.HAND
    assert p1.mana_pool.total() == mana


def test_additional_cost_without_picks_falls_back_to_first_card():
    eng, p1, lancer, gy = _lancer()
    eng.cast_spell(p1, lancer)
    assert gy[0].zone == Zone.EXILE and gy[1].zone == Zone.GRAVEYARD


def test_additional_cost_offer_lists_pool_and_session_applies_picks():
    eng, p1, lancer, gy = _lancer()
    action = next(a for a in eng.legal_actions(p1)
                  if a.get("type") == "cast_spell" and a.get("instance_id") == lancer.instance_id)
    cost = action["graveyard_exile_cost"]
    assert cost["count"] == 1
    assert {o["instance_id"] for o in cost["options"]} == {c.instance_id for c in gy}
    session = GameSession(eng, mode="replay", require_setup=False)
    session.apply_action({"type": "cast_spell", "instance_id": lancer.instance_id,
                          "graveyard_exile_choices": [gy[1].instance_id]})
    assert gy[1].zone == Zone.EXILE and gy[0].zone == Zone.GRAVEYARD


# --- Escape ---------------------------------------------------------------------------------------------------------

def test_escape_pick_is_honoured():
    eng, p1, bolt, fuel = _escape()
    eng.cast_spell(p1, bolt, graveyard_exile_choices=[f.instance_id for f in fuel[1:]])
    assert all(f.zone == Zone.EXILE for f in fuel[1:])
    assert fuel[0].zone == Zone.GRAVEYARD


@pytest.mark.parametrize("bad", ["the_spell", "duplicate", "too_few"])
def test_escape_invalid_picks_rejected_without_state_change(bad):
    eng, p1, bolt, fuel = _escape()
    picks = {"the_spell": [bolt.instance_id, fuel[0].instance_id, fuel[1].instance_id], "duplicate": [fuel[0].instance_id] * ESCAPE_EXILE_COUNT,
             "too_few": [fuel[0].instance_id]}[bad]
    before, mana = _gy_ids(p1), p1.mana_pool.total()
    with pytest.raises(ValueError):
        eng.cast_spell(p1, bolt, graveyard_exile_choices=picks)
    assert _gy_ids(p1) == before and not eng.state.stack
    assert p1.mana_pool.total() == mana


def test_escape_without_picks_falls_back_to_first_other_card():
    eng, p1, bolt, fuel = _escape()
    eng.cast_spell(p1, bolt)
    assert all(f.zone == Zone.EXILE for f in fuel[:ESCAPE_EXILE_COUNT]) and fuel[-1].zone == Zone.GRAVEYARD


def test_escape_offer_lists_other_cards_only():
    eng, p1, bolt, fuel = _escape()
    action = next(a for a in eng.legal_actions(p1)
                  if a.get("type") == "cast_spell" and a.get("instance_id") == bolt.instance_id)
    cost = action["graveyard_exile_cost"]
    assert cost["count"] == ESCAPE_EXILE_COUNT
    assert {o["instance_id"] for o in cost["options"]} == {c.instance_id for c in fuel}


def test_smart_bot_fills_the_cast_pick():
    from mtg_analyzer.services.smart_bot2.choices import fill_costs

    class Ctx:
        effect_text = staticmethod(lambda action: "")
        value = staticmethod(lambda option: option["mana_value"])

    options = [{"instance_id": 1, "mana_value": 5}, {"instance_id": 2, "mana_value": 0}]
    built = fill_costs(Ctx, {"type": "cast_spell", "graveyard_exile_cost": {"count": 1, "options": options}})
    assert built["graveyard_exile_choices"] == [2]


# --- two exile costs on one cast -------------------------------------------------------------------------------------

def _escape_with_additional(n_fuel):
    from mtg_analyzer.game.costs import parse_activation_cost

    eng, p1, bolt, fuel = _escape(n_fuel)
    bolt.additional_cast_cost = parse_activation_cost({"exile_from_graveyard": {"count": 1}})
    return eng, p1, bolt, fuel


def test_two_exile_costs_never_claim_the_same_card():
    eng, p1, bolt, fuel = _escape_with_additional(ESCAPE_EXILE_COUNT + 1)
    eng.cast_spell(p1, bolt, graveyard_exile_choices=[f.instance_id for f in fuel[:ESCAPE_EXILE_COUNT]])
    assert [f.zone for f in fuel] == [Zone.EXILE] * (ESCAPE_EXILE_COUNT + 1)
    assert len(p1.exile) == ESCAPE_EXILE_COUNT + 1  # sum of both counts, all distinct


def test_two_exile_costs_without_picks_are_distinct_too():
    eng, p1, bolt, fuel = _escape_with_additional(ESCAPE_EXILE_COUNT + 1)
    eng.cast_spell(p1, bolt)
    assert len(p1.exile) == ESCAPE_EXILE_COUNT + 1


def test_two_exile_costs_fail_closed_when_the_pool_cannot_cover_both():
    eng, p1, bolt, fuel = _escape_with_additional(ESCAPE_EXILE_COUNT)
    before = _gy_ids(p1)
    with pytest.raises(ValueError):
        eng.cast_spell(p1, bolt)
    assert _gy_ids(p1) == before and not p1.exile and not eng.state.stack

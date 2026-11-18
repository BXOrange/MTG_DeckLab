"""PAR-285 (v980): stat bounds on a creature object filter beyond a literal "N or less".

* a measured bound, either stat, either direction: "power greater than or equal to your life total" (Blazing Hope),
  "power less than or equal to the number of treasure counters on ~" (Legacy's Allure), "power greater than / less than
  the number of cards in your hand" (Nightmare Unmaking's mass modes) -- `stat_count_bound`;
* "power **or** toughness N or greater/less" (Repel Calamity, Warping Wail) -- either stat meets the bound (RULE 208.1);
* "**total** power and toughness N or less" (Cut Down) -- their sum.

Tests run parser -> binder -> targeting -> engine on the real cards' text, with matching AND non-matching candidates.
Every behaviour test fails when `combat.matches_object_filter` stops reading the new keys (they are then ignored)."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import targeting
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.test_par285_sequential_another_target import _card, _hand, _put, _session

NEW_CARDS = ["Legacy's Allure", "Blazing Hope", "Repel Calamity", "Warping Wail", "Cut Down", "Nightmare Unmaking"]


def _real(name: str):
    card = CardDatabase(DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    return card


def _hand_real(state, name: str, owner: str = "p1"):
    return _hand(state, _real(name), owner)


def _bear(name: str, power: int, toughness: int):
    return _card(name, "Creature — Bear", power=power, toughness=toughness)


def _offered(state, spell) -> set:
    (entry,) = targeting.requirements_with_targets(state, "p1", spell)
    return {o["instance_id"] for o in entry["options"]}


@pytest.mark.parametrize("name", NEW_CARDS)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_real(name)).modeled is True


def test_parse_shapes():
    (spec,) = match_clause("exile target creature with power greater than or equal to your life total")
    assert spec.params["creature_filter"] == {
        "stat_count_bound": {"stat": "power", "cmp": "ge", "selector": "your_life_total"}}
    (spec,) = match_clause("destroy target creature with power or toughness 4 or greater")
    assert spec.params["creature_filter"] == {"min_power_or_toughness": 4}
    (spec,) = match_clause("destroy target creature with total power and toughness 5 or less")
    assert spec.params["creature_filter"] == {"max_total_power_toughness": 5}
    # adversarial: an amount the engine cannot measure, and a bound with no direction, stay unclaimed
    assert match_clause("destroy target creature with power greater than the number of frobs on ~") is None
    assert match_clause("destroy target creature with power or toughness 4") is None


def test_blazing_hope_compares_power_to_the_casters_life_total():
    _, engine, state = _session()
    p1 = state.player_by_id("p1")
    p1.life = 4
    spell = _hand_real(state, "Blazing Hope")
    fat = _put(state, _bear("Fat", 5, 1), "p2")
    equal = _put(state, _bear("Equal", 4, 1), "p2")
    small = _put(state, _bear("Small", 3, 9), "p2")
    assert _offered(state, spell) == {fat.instance_id, equal.instance_id}
    p1.mana_pool.add_many({"W": 1})
    engine.cast_spell(p1, spell, targets=[equal])
    engine.rules.resolve_top_of_stack()
    assert equal.zone == Zone.EXILE and fat.zone == Zone.BATTLEFIELD and small.zone == Zone.BATTLEFIELD
    p1.life = 6  # a higher life total shrinks the offer: the bound is measured live, not baked in
    spell2 = _hand_real(state, "Blazing Hope")
    assert _offered(state, spell2) == set()


def test_legacys_allure_steals_a_creature_up_to_its_treasure_counters():
    _, engine, state = _session()
    p1 = state.player_by_id("p1")
    allure = _put(state, _real("Legacy's Allure"), "p1")
    allure.counters["treasure"] = 3
    big = _put(state, _bear("Big", 4, 4), "p2")
    fit = _put(state, _bear("Fit", 3, 5), "p2")
    tiny = _put(state, _bear("Tiny", 1, 1), "p2")
    with pytest.raises(ValueError):  # RULE 601.2c: a power-4 creature is no legal target against 3 counters
        engine.activate_ability(p1, allure, 0, targets=[big])
    assert allure.zone == Zone.BATTLEFIELD  # the illegal announcement was rejected before the sacrifice cost
    engine.activate_ability(p1, allure, 0, targets=[fit])
    engine.rules.resolve_top_of_stack()
    assert fit.controller_id == "p1" and big.controller_id == "p2"
    assert allure.zone == Zone.GRAVEYARD


def test_repel_calamity_needs_either_stat_at_four():
    _, engine, state = _session()
    p1 = state.player_by_id("p1")
    spell = _hand_real(state, "Repel Calamity")
    power = _put(state, _bear("Power", 4, 1), "p2")
    tough = _put(state, _bear("Tough", 1, 4), "p2")
    neither = _put(state, _bear("Neither", 3, 3), "p2")
    assert _offered(state, spell) == {power.instance_id, tough.instance_id}
    p1.mana_pool.add_many({"W": 1, "C": 1})
    engine.cast_spell(p1, spell, targets=[tough])
    engine.rules.resolve_top_of_stack()
    assert tough.zone == Zone.GRAVEYARD and neither.zone == Zone.BATTLEFIELD and power.zone == Zone.BATTLEFIELD


def test_warping_wail_exile_mode_needs_either_stat_at_one_or_less():
    _, engine, state = _session()
    p1 = state.player_by_id("p1")
    spell = _hand_real(state, "Warping Wail")
    thin = _put(state, _bear("Thin", 5, 1), "p2")
    weak = _put(state, _bear("Weak", 1, 5), "p2")
    solid = _put(state, _bear("Solid", 2, 2), "p2")
    p1.mana_pool.add_many({"C": 2})
    engine.cast_spell(p1, spell, targets=[weak], mode=0)
    engine.rules.resolve_top_of_stack()
    assert weak.zone == Zone.EXILE and thin.zone == Zone.BATTLEFIELD and solid.zone == Zone.BATTLEFIELD
    assert targeting._creature_matches_filter(thin, {"max_power_or_toughness": 1}, reference=spell, state=state)
    assert not targeting._creature_matches_filter(solid, {"max_power_or_toughness": 1}, reference=spell, state=state)


def test_cut_down_bounds_the_sum_not_either_stat():
    _, engine, state = _session()
    p1 = state.player_by_id("p1")
    spell = _hand_real(state, "Cut Down")
    ok = _put(state, _bear("Sum Five", 3, 2), "p2")
    lopsided = _put(state, _bear("Sum Six", 5, 1), "p2")
    _put(state, _bear("Sum Eight", 4, 4), "p2")
    assert _offered(state, spell) == {ok.instance_id}
    assert lopsided.instance_id not in _offered(state, spell)
    p1.mana_pool.add_many({"B": 1})
    engine.cast_spell(p1, spell, targets=[ok])
    engine.rules.resolve_top_of_stack()
    assert ok.zone == Zone.GRAVEYARD and lopsided.zone == Zone.BATTLEFIELD


@pytest.mark.parametrize("mode,gone,kept", [(0, {"Giant"}, {"Mouse", "Mid"}), (1, {"Mouse"}, {"Giant", "Mid"})])
def test_nightmare_unmaking_modes_exile_by_hand_size(mode, gone, kept):
    _, engine, state = _session()
    p1 = state.player_by_id("p1")
    p1.hand.clear()
    spell = _hand_real(state, "Nightmare Unmaking")
    for _ in range(2):  # hand size after casting: 2 -> power > 2 (mode 0) or power < 2 (mode 1)
        p1.hand.append(GameObject(_card("Filler", "Instant"), owner_id="p1", zone=Zone.HAND))
    giant = _put(state, _bear("Giant", 5, 5), "p2")
    mouse = _put(state, _bear("Mouse", 1, 1), "p2")
    mid = _put(state, _bear("Mid", 2, 2), "p1")
    p1.mana_pool.add_many({"B": 2, "C": 3})
    engine.cast_spell(p1, spell, mode=mode)
    engine.rules.resolve_top_of_stack()
    by_name = {"Giant": giant, "Mouse": mouse, "Mid": mid}
    assert {n for n, o in by_name.items() if o.zone == Zone.EXILE} == gone
    assert {n for n, o in by_name.items() if o.zone == Zone.BATTLEFIELD} == kept


def test_temporary_insanity_steals_untaps_and_hastes_a_small_creature():
    _, engine, state = _session()
    p1 = state.player_by_id("p1")
    p1.graveyard.clear()
    for _ in range(3):  # three cards in the caster's graveyard: power 2 or less qualifies, power 3 does not
        p1.graveyard.append(GameObject(_card("Filler", "Instant"), owner_id="p1", zone=Zone.GRAVEYARD))
    spell = _hand_real(state, "Temporary Insanity")
    small = _put(state, _bear("Small", 2, 2), "p2")
    small.tapped = True
    big = _put(state, _bear("Big", 3, 3), "p2")
    assert _offered(state, spell) == {small.instance_id}
    p1.mana_pool.add_many({"R": 1, "C": 3})
    engine.cast_spell(p1, spell, targets=[small])
    engine.rules.resolve_top_of_stack()
    assert small.controller_id == "p1" and small.tapped is False
    engine.recompute_continuous_effects()
    assert "haste" in small.granted_keywords  # "That creature gains haste until end of turn"
    assert big.controller_id == "p2"
    state.player_by_id("p1").graveyard.clear()  # the bound is live: an emptied graveyard offers nothing
    assert _offered(state, _hand_real(state, "Temporary Insanity")) == set()


def test_zar_ojanen_counters_only_creatures_below_the_domain_count():
    _, engine, state = _session()
    zar = _put(state, _real("Zar Ojanen, Scion of Efrava"), "p1")
    for land_type in ("Plains", "Island", "Swamp"):  # domain 3: toughness 1 and 2 qualify, toughness 3 does not
        _put(state, _card(land_type, f"Basic Land — {land_type}"), "p1").card.is_land = True
    low = _put(state, _bear("Low", 2, 1), "p1")
    mid = _put(state, _bear("Mid", 2, 2), "p1")
    high = _put(state, _bear("High", 2, 3), "p1")
    foe = _put(state, _bear("Foe", 2, 1), "p2")
    engine.rules.set_tapped(zar, True)  # "whenever ~ becomes tapped" fires from the tap transition (RULE 603.2)
    engine.resolve_until_stable()
    assert _counters(low) == 1 and _counters(mid) == 1
    assert _counters(high) == 0 and _counters(foe) == 0


def _counters(obj) -> int:
    return obj.plus_one_counters  # the +1/+1 counter total (RULE 122.1)

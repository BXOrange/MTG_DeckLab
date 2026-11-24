"""PAR-285: "target creature with <quality> can't block this turn" carries the target's quality slot.

Covers the dynamic power comparators ("less than or equal to ~'s power" / "the number of <things> you control")
that the shared target grammar already reads, now carried by the can't-block row (it used to drop the slot)."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import targeting
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.game import creature, make_engine, obj_on_battlefield


def test_power_vs_source_power_filter_is_carried():
    specs = match_clause("target creature with power less than or equal to ~'s power can't block this turn")
    assert specs is not None and specs[0].type == "cant_block_this_turn"
    assert specs[0].params["creature_filter"] == {"power_vs_reference": "less_equal"}


def test_power_vs_count_filter_is_carried():
    specs = match_clause(
        "target creature an opponent controls with power less than or equal to the number of warriors you control"
        " can't block this turn")
    assert specs is not None
    filt = specs[0].params["creature_filter"]
    assert specs[0].params["target_kind"] == "creature_you_dont_control"
    assert filt["power_le_count_selector"]["filter"] == {"subtype": "warrior"}


def test_unknown_count_phrase_is_not_claimed():
    assert match_clause(
        "target creature with power less than or equal to the number of frobnicators can't block this turn") is None


def test_targeting_enforces_source_power_bound():
    engine = make_engine([creature()], [creature()])
    state = engine.state
    source = obj_on_battlefield(state, engine, creature("Khenra", power=2, toughness=2), "p1")
    weak = obj_on_battlefield(state, engine, creature("Elf", power=2, toughness=2), "p2")
    strong = obj_on_battlefield(state, engine, creature("Ogre", power=3, toughness=3), "p2")
    filt = {"power_vs_reference": "less_equal"}

    def ok(obj):
        return targeting._creature_matches_filter(obj, filt, reference=source, state=state, controller_id="p1")

    assert ok(weak) and not ok(strong)


@pytest.mark.parametrize("name", ["Earthshaker Khenra", "Goma Fada Vanguard", "Radha's Firebrand"])
def test_real_cards_are_modeled(name):
    card = CardDatabase(DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    assert parse_oracle(card).modeled is True


# --- parser -> binder -> targeting, on the real cards -----------------------------------------------


def _bound_cant_block(name: str):
    from mtg_analyzer.game.binding.core import build_effects

    card = CardDatabase(DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    specs = [e for ab in parse_oracle(card).specs for e in ab.effects if e.type == "cant_block_this_turn"]
    assert len(specs) == 1, name
    return build_effects(specs, None)[0]


def _legal_ids(state, effect, source):
    return {t["instance_id"] for t in targeting.legal_targets(state, "p1", effect.target_spec, source=source)}


def test_ground_rift_cannot_target_a_flyer():
    effect = _bound_cant_block("Ground Rift")
    engine = make_engine([creature()], [creature()])
    state = engine.state
    source = obj_on_battlefield(state, engine, creature("Src"), "p1")
    walker = obj_on_battlefield(state, engine, creature("Walker"), "p2")
    flyer = obj_on_battlefield(state, engine, creature("Bird", keywords=["Flying"]), "p2")
    engine.recompute_continuous_effects()
    legal = _legal_ids(state, effect, source)
    assert walker.instance_id in legal and flyer.instance_id not in legal


def test_earthshaker_khenra_cannot_target_greater_power():
    effect = _bound_cant_block("Earthshaker Khenra")
    engine = make_engine([creature()], [creature()])
    state = engine.state
    source = obj_on_battlefield(state, engine, creature("Khenra", power=2, toughness=1), "p1")
    weak = obj_on_battlefield(state, engine, creature("Elf", power=2, toughness=2), "p2")
    strong = obj_on_battlefield(state, engine, creature("Ogre", power=3, toughness=3), "p2")
    engine.recompute_continuous_effects()
    legal = _legal_ids(state, effect, source)
    assert weak.instance_id in legal and strong.instance_id not in legal


def test_goma_fada_vanguard_count_bound_and_opponent_scope():
    effect = _bound_cant_block("Goma Fada Vanguard")
    engine = make_engine([creature()], [creature()])
    state = engine.state
    source = obj_on_battlefield(state, engine, creature("Goma", type_line="Creature — Human Warrior"), "p1")
    mine = obj_on_battlefield(state, engine, creature("Mine", power=1, toughness=1), "p1")
    small = obj_on_battlefield(state, engine, creature("Small", power=1, toughness=1), "p2")
    big = obj_on_battlefield(state, engine, creature("Big", power=4, toughness=4), "p2")
    engine.recompute_continuous_effects()
    legal = _legal_ids(state, effect, source)
    assert small.instance_id in legal and big.instance_id not in legal and mine.instance_id not in legal

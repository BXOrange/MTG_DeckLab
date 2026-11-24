"""PAR-284 milestone 16: "up to X target <things>, where X is the number of verse counters on ~" (RULE 601.2c, 602.2b).

Recantation / Rumbling Crescendo / Serra's Liturgy sacrifice themselves as a cost, but the targets are announced
before costs are paid, so the number of targets is the counters still on the source then."""
from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import attach_to_object
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.test_par284_counter_amounts import _board_creature
from tests.test_par284_this_way_windows import _card, _engine

CRESCENDO = "{R}, Sacrifice ~: Destroy up to X target lands, where X is the number of verse counters on ~."
LITURGY = "{W}, Sacrifice ~: Destroy up to X target artifacts and/or enchantments, where X is the number of verse counters on ~."
RECANTATION = "{U}, Sacrifice ~: Return up to X target permanents to their owners' hands, where X is the number of verse counters on ~."


@pytest.mark.parametrize("oracle", [CRESCENDO, LITURGY, RECANTATION])
def test_verse_targets_are_modeled(oracle):
    assert parse_oracle(_card("Verse", "Enchantment", oracle)).modeled


def test_target_count_is_the_source_counter_selector():
    [spec] = parse_effect_body("destroy up to x target lands, where x is the number of verse counters on ~")
    assert spec.params["count_selector"] == "source_verse_counters"


@pytest.mark.parametrize("phrase", [
    "destroy up to x target lands, where x is the number of +1/+1 counters on ~",
    "destroy up to x target lands, where x is the number of verse counters on target land",
])
def test_other_counter_referents_are_not_announce_time_counts(phrase):
    [spec] = parse_effect_body(phrase) or [None]
    assert spec is None or spec.params.get("count_selector") != "source_verse_counters"


def _crescendo(eng, counters):
    card = _card("Rumbling Crescendo", "Enchantment", CRESCENDO)
    result = parse_oracle(card)
    src = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    src.counters["verse"] = counters
    attach_to_object(src, result.specs)
    eng.state.battlefield.append(src)
    eng.state.players[0].mana_pool.add_many({"R": 1})
    lands = [_board_creature(eng, _card(f"Land{i}", "Land", is_land=True), "p2") for i in range(3)]
    return src, lands


def test_destroys_as_many_lands_as_counters_while_the_source_is_still_there():
    eng = _engine()
    src, lands = _crescendo(eng, 2)
    eng.activate_ability(eng.state.players[0], src, 0, targets=lands[:2])
    eng.resolve_until_stable()
    assert src.zone == Zone.GRAVEYARD
    assert [land.zone for land in lands] == [Zone.GRAVEYARD, Zone.GRAVEYARD, Zone.BATTLEFIELD]


def test_more_targets_than_counters_is_refused():
    eng = _engine()
    src, lands = _crescendo(eng, 1)
    with pytest.raises(ValueError):
        eng.activate_ability(eng.state.players[0], src, 0, targets=lands[:2])
    assert src.zone == Zone.BATTLEFIELD


def test_no_counters_means_no_targets_and_the_ability_still_resolves():
    eng = _engine()
    src, lands = _crescendo(eng, 0)
    eng.activate_ability(eng.state.players[0], src, 0, targets=[])
    eng.resolve_until_stable()
    assert all(land.zone == Zone.BATTLEFIELD for land in lands)

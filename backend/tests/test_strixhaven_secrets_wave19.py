"""Secrets of Strixhaven — playability batch, wave 19.

Wave 19 (PARSER_VERSION 294 -> 295): "Attacking <subtype> you control
get/have …" (Blight Mound, Dire Fleet Neckbreaker, Elderfang Venom,
Crossway Troublemakers). `static_handlers._scope` strips a leading
"attacking" into a new `_Scope.attacking` flag; `_scope_params` folds it
into an ``attacking_creatures_you_control[_of_type_<subtype>]`` `affects`
selector, resolved by new branches in `continuous`'s anthem resolver.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def test_attacking_subtype_anthem_and_grant():
    specs = static_effect_specs("attacking pests you control get +1/+0 and have menace")
    types = {s.type: s.params for s in specs}
    assert types["anthem"]["affects"] == "attacking_creatures_you_control_of_type_pest"
    assert types["anthem"]["power"] == 1 and types["anthem"]["toughness"] == 0
    assert types["grant_keyword"]["keywords"] == ["menace"]
    assert types["grant_keyword"]["affects"] == "attacking_creatures_you_control_of_type_pest"
    assert "subtype" not in types["anthem"]


def test_attacking_bare_creatures_and_grant_only():
    a = static_effect_specs("attacking creatures you control get +1/+1")
    assert a[0].params["affects"] == "attacking_creatures_you_control"
    g = static_effect_specs("attacking elves you control have deathtouch")
    assert g[0].type == "grant_keyword"
    assert g[0].params["affects"] == "attacking_creatures_you_control_of_type_elf"


def test_non_attacking_anthem_unchanged():
    specs = static_effect_specs("elves you control get +1/+1")
    assert specs[0].params["affects"] == "creatures_you_control"
    assert specs[0].params["subtype"] == "Elf"


@pytest.mark.parametrize("name", [
    "Blight Mound", "Dire Fleet Neckbreaker", "Elderfang Venom", "Crossway Troublemakers",
])
def test_real_cards_modeled(name):
    r = parse_oracle(_db().get_card(name))
    assert r.coverage != UNMODELED, r.unclaimed


def test_anthem_scopes_to_attacking_subtype_only_at_runtime():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    src = GameObject(card=Card(id="bm", name="Blight Mound", type_line="Artifact"),
                     owner_id=p1.id, zone=Zone.BATTLEFIELD)
    src.controller_id = p1.id
    eng.state.add_to_battlefield(src)
    src.static_effects.extend(build_effects([EffectSpec("anthem", {
        "power": 1, "toughness": 0,
        "affects": "attacking_creatures_you_control_of_type_pest"})], src))

    def mk(oid, sub, atk):
        o = GameObject(card=Card(id=oid, name=oid, type_line=f"Creature — {sub}",
                                 is_creature=True, power=2, toughness=2),
                       owner_id=p1.id, zone=Zone.BATTLEFIELD)
        o.controller_id = p1.id
        o.attacking = atk
        eng.state.add_to_battlefield(o)
        return o

    pest_atk = mk("pa", "Pest", True)
    pest_idle = mk("pi", "Pest", False)
    goblin_atk = mk("ga", "Goblin", True)
    eng.recompute_continuous_effects()
    assert (pest_atk.power, pest_atk.toughness) == (3, 2)
    assert (pest_idle.power, pest_idle.toughness) == (2, 2)
    assert (goblin_atk.power, goblin_atk.toughness) == (2, 2)

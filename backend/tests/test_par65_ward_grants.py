"""PAR-65 — parametric-keyword static grants, starting with Ward `<cost>`
(RULE 702.21b).

`continuous.py`'s grant loop already applied ``ward_cost`` generically to
*any* `affected_objects(state, ability)` result (the comment there even
cites Hexing Squelcher's group-scoped "Other creatures you control have
'Ward—Pay 2 life.'\"" as already working) — the real gap was entirely on
the parser side: every keyword-list regex in this family
(`_ATTACHED_ANTHEM_RE`, `_ATTACHED_GRANT_RE`, `_ANTHEM_RE`, `_GRANT_RE`,
`_MULTI_PERMANENT_TYPE_GRANT_RE`) used a bare-word character class
(``[a-z][a-z, ]*``) that couldn't even capture "ward {2}"'s braces/digits,
and `_flag_keywords` itself fails closed on any parametric keyword by
design (its own docstring named Ward as the example). Fixed by widening
each regex's keyword-list capture and adding `_flag_keywords_and_ward`, a
sibling that peels "ward `<cost>`" entries out of the list first (so a
mixed list — Ward plus an ordinary flag keyword — still works) and hands
the rest to the unmodified `_flag_keywords`.

Reference: mtg_analyzer/parser/oracle/catalogue/static_handlers.py,
mtg_analyzer/game/continuous.py (`ward_cost` grant loop, unmodified).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle.catalogue.static_handlers import (
    _flag_keywords_and_ward,
    static_effect_specs,
)
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def _engine(*player_ids):
    players = [Player(id=pid, life=20) for pid in player_ids]
    state = GameState(players=players)
    return GameEngine(state), state


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


# ---------------------------------------------------------------------------
# _flag_keywords_and_ward — the shared extraction helper
# ---------------------------------------------------------------------------


def test_bare_ward_extracted():
    assert _flag_keywords_and_ward("ward {2}") == ([], "{2}")


def test_ward_mixed_with_a_flag_keyword():
    # Brotherhood Regalia mixes ward into a list with ordinary flag keywords.
    assert _flag_keywords_and_ward("ward {2} and flying") == (["flying"], "{2}")


def test_plain_keyword_list_unaffected():
    assert _flag_keywords_and_ward("flying, trample") == (["flying", "trample"], None)


def test_two_wards_fail_closed():
    assert _flag_keywords_and_ward("ward {1}, ward {2}") is None


def test_unrecognised_keyword_alongside_ward_fails_closed():
    assert _flag_keywords_and_ward("ward {1}, some made up ability") is None


# ---------------------------------------------------------------------------
# Parser recognition, one per widened regex family
# ---------------------------------------------------------------------------


def test_attached_bare_ward_grant():
    specs = static_effect_specs("enchanted permanent has ward {1}.")
    assert specs == [
        EffectSpec("grant_keyword", {"affects": "attached_permanent", "ward_cost": "{1}"})
    ]


def test_attached_anthem_plus_ward():
    specs = static_effect_specs("equipped creature gets +2/+1 and has ward {2}.")
    assert len(specs) == 2
    assert specs[0].type == "anthem"
    assert specs[1].params == {"affects": "attached_permanent", "ward_cost": "{2}"}


def test_group_bare_ward_grant():
    specs = static_effect_specs("artifacts you control have ward {1}.")
    assert len(specs) == 1
    assert specs[0].type == "grant_keyword"
    assert specs[0].params["ward_cost"] == "{1}"
    assert specs[0].params["affects"] == "artifacts_you_control"


def test_group_anthem_plus_ward():
    specs = static_effect_specs("other warriors you control get +1/+1 and have ward {1}.")
    assert len(specs) == 2
    assert specs[1].params["ward_cost"] == "{1}"


def test_multi_permanent_type_ward_grant():
    specs = static_effect_specs("artifacts and creatures you control have ward {1}.")
    assert len(specs) == 1
    assert specs[0].params["ward_cost"] == "{1}"
    assert set(specs[0].params["card_type"]) == {"artifact", "creature"}


def test_ordinary_flag_grant_unaffected_by_widened_regex():
    # The widened character class must not start over-matching a plain,
    # ward-free keyword grant.
    specs = static_effect_specs("equipped creature has indestructible and is goaded.")
    assert len(specs) == 2
    assert specs[0].params["keywords"] == ["indestructible"]


# ---------------------------------------------------------------------------
# Execute-level: the grant actually stamps `GameObject.granted_ward_cost`
# ---------------------------------------------------------------------------


def test_ward_grant_stamps_granted_ward_cost_live():
    engine, state = _engine("p1")
    source = _bf(state, Card(
        id="Bench Ward Source", name="Bench Ward Source", type_line="Enchantment",
        oracle_text="Artifacts you control have ward {1}.",
    ))
    target = _bf(state, Card(
        id="Bench Artifact Target", name="Bench Artifact Target", type_line="Artifact",
    ))
    non_target = _bf(state, Card(
        id="Bench Creature Non-Target", name="Bench Creature Non-Target",
        type_line="Creature — Bear", is_creature=True, power=1, toughness=1,
    ))
    continuous.recompute(state)
    assert target.granted_ward_cost == "{1}"
    assert non_target.granted_ward_cost is None


# ---------------------------------------------------------------------------
# End-to-end: real cached cards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", [
    "Elder Owyn Lyons", "Hardlight Containment", "Crystal Carapace",
    "Armguard Familiar", "Leather Armor", "Plate Armor", "A-Plate Armor",
    "A-Kargan Warleader", "Star Whale", "Storvald, Frost Giant Jarl",
    "Thorin Oakenshield",
])
def test_ward_grant_cards_modeled(name):
    r = parse_oracle(_db().get_card(name))
    assert r.coverage != UNMODELED, r.unclaimed

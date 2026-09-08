"""RULE 613.7/305.6 interaction between an *additive* board-wide land-type
grant (Urborg, Tomb of Yawgmoth/Yavimaya, Cradle of Growth — "Each land is a
Swamp/Forest in addition to its other land types.") and a full layer-4 type
*overwrite* (Blood Moon/Magus of the Moon — "Nonbasic lands are Mountains.").

Both families are `type_change` `EffectSpec`s (`parser/oracle/catalogue/
static_handlers.py`'s `_LAND_IS_BASIC_TYPE_RE`/`_TYPE_OVERWRITE_RE`), and each
carries its own RULE 305.6 intrinsic mana ability — not as a hand-paired
`grant_mana_ability` spec, but derived generically off the object's final,
timestamp-resolved subtype set (`game/mana_abilities.py`'s
`_derived_basic_mana_options`, consulting `continuous.has_subtype`). RULE
613.7 timestamp order decides which of the two land-type effects "wins" when
both apply to the same land: an additive grant that enters *after* an
overwrite stacks its type on top of it (a land can end up "Mountain Swamp"),
while one that entered *before* the overwrite is wiped out by it, exactly
like a real Blood Moon + Urborg board.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.mana_abilities import mana_options_for
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

pytestmark = pytest.mark.skipif(
    not DEFAULT_DB_PATH.exists(), reason="card cache not present in this environment"
)


def _card(name: str) -> Card:
    db = CardDatabase(DEFAULT_DB_PATH)
    card = db.get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not present in the local card cache")
    return card


def _battlefield(state, card: Card, controller: str = "p1") -> GameObject:
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _engine() -> GameEngine:
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=40, starting_hand=0,
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _plain_nonbasic_land(name: str = "Test Nonbasic Land") -> Card:
    """A nonbasic land with no printed subtype/mana ability of its own, so
    every type/mana result observed comes purely from the two statics under
    test."""
    return Card(id=name, name=name, type_line="Land", is_land=True)


def test_yavimaya_urborg_family_modeled():
    for name in ("Yavimaya, Cradle of Growth", "Urborg, Tomb of Yawgmoth"):
        result = parse_oracle(_card(name))
        assert result.modeled, (name, result.unclaimed)


def test_yavimaya_grants_forest_type_and_green_mana():
    eng = _engine()
    state = eng.state
    _battlefield(state, _card("Yavimaya, Cradle of Growth"), controller="p1")
    land = _battlefield(state, _plain_nonbasic_land(), controller="p2")

    eng.recompute_continuous_effects()
    assert continuous.has_subtype(land, "Forest") is True
    assert {"G": 1} in mana_options_for(land, state)


def test_urborg_grants_swamp_type_and_black_mana():
    eng = _engine()
    state = eng.state
    _battlefield(state, _card("Urborg, Tomb of Yawgmoth"), controller="p1")
    land = _battlefield(state, _plain_nonbasic_land(), controller="p2")

    eng.recompute_continuous_effects()
    assert continuous.has_subtype(land, "Swamp") is True
    assert {"B": 1} in mana_options_for(land, state)


def test_urborg_before_blood_moon_is_wiped_by_the_overwrite():
    """Urborg's additive Swamp grant has the *older* timestamp here (it
    entered first) — Blood Moon's later, full RULE 613.5 overwrite replaces
    the land's subtype set outright, so the earlier Swamp grant is gone and
    only Mountain (and its {R}) remains."""
    eng = _engine()
    state = eng.state
    _battlefield(state, _card("Urborg, Tomb of Yawgmoth"), controller="p1")
    land = _battlefield(state, _plain_nonbasic_land(), controller="p2")
    _battlefield(state, _card("Blood Moon"), controller="p1")

    eng.recompute_continuous_effects()
    assert continuous.has_subtype(land, "Mountain") is True
    assert continuous.has_subtype(land, "Swamp") is False
    options = mana_options_for(land, state)
    assert {"R": 1} in options
    assert {"B": 1} not in options


def test_urborg_after_blood_moon_stacks_swamp_onto_mountain():
    """The same board, entering order reversed — Blood Moon's overwrite now
    has the *older* timestamp, so Urborg's Swamp grant applies afterwards and
    stacks on top of it instead of being erased: the land ends up both
    Mountain and Swamp, tapping for either {R} or {B}."""
    eng = _engine()
    state = eng.state
    _battlefield(state, _card("Blood Moon"), controller="p1")
    land = _battlefield(state, _plain_nonbasic_land(), controller="p2")
    _battlefield(state, _card("Urborg, Tomb of Yawgmoth"), controller="p1")

    eng.recompute_continuous_effects()
    assert continuous.has_subtype(land, "Mountain") is True
    assert continuous.has_subtype(land, "Swamp") is True
    options = mana_options_for(land, state)
    assert {"R": 1} in options
    assert {"B": 1} in options

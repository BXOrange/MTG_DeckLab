"""BUG-27 -- RULE 110.4: a battle card is a permanent card, so a "target permanent card in your graveyard"
(and "nonland permanent card") target must offer it; a land card stays out of the nonland variant."""

from __future__ import annotations

import pytest

from mtg_analyzer.game import targeting
from mtg_analyzer.game.targeting import TargetSpec
from mtg_analyzer.models.cards import card_query
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone

from tests.support.game import make_engine

BATTLE = "Invasion of Alara // Awaken the Maelstrom"
RETURNER = "Elvish Regrower"  # "return target permanent card from your graveyard to your hand"


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _bury(eng, card):
    obj = GameObject(card, owner_id="p1", zone=Zone.GRAVEYARD)
    eng.state.player_by_id("p1").graveyard.append(obj)
    return obj


def _offered(eng, kind):
    spec = TargetSpec(kind=kind)
    return {t["instance_id"] for t in targeting.legal_targets(eng.state, "p1", spec)}


@pytest.mark.parametrize("kind", ["graveyard_permanent", "graveyard_nonland_permanent"])
def test_real_battle_card_is_offered_from_graveyard(kind):
    battle = _named(BATTLE)
    assert battle is not None and _named(RETURNER) is not None
    eng = make_engine([battle], [battle], hand=0)
    obj = _bury(eng, battle)
    assert obj.instance_id in _offered(eng, kind)


def test_land_card_only_in_permanent_not_nonland_permanent():
    land = Card(id="forest", name="Forest", type_line="Basic Land — Forest", is_land=True)
    eng = make_engine([land], [land], hand=0)
    obj = _bury(eng, land)
    assert obj.instance_id in _offered(eng, "graveyard_permanent")
    assert obj.instance_id not in _offered(eng, "graveyard_nonland_permanent")


def test_instant_is_not_a_permanent_card():
    spell = Card(id="bolt", name="Bolt", type_line="Instant", is_instant=True)
    eng = make_engine([spell], [spell], hand=0)
    obj = _bury(eng, spell)
    assert obj.instance_id not in _offered(eng, "graveyard_permanent")


def test_shared_predicate_reads_card_types_not_subtypes():
    battle = Card(id="b", name="B", type_line="Battle — Siege")
    arbor = Card(id="a", name="Dryad Arbor", type_line="Land Creature — Forest Dryad", is_land=True, is_creature=True)
    sorcery = Card(id="s", name="S", type_line="Sorcery — Arcane")
    assert card_query.is_permanent_card(battle) and card_query.is_nonland_permanent_card(battle)
    assert card_query.is_permanent_card(arbor) and not card_query.is_nonland_permanent_card(arbor)
    assert not card_query.is_permanent_card(sorcery)


def test_opponents_battle_is_a_nonland_permanent_target_you_dont_control():
    """RULE 110.4 on the battlefield: "target spell or nonland permanent you don't control" offers a battle."""
    battle = Card(id="b", name="B", type_line="Battle — Siege")
    land = Card(id="forest", name="Forest", type_line="Basic Land — Forest", is_land=True)
    eng = make_engine([battle], [battle], hand=0)
    theirs = GameObject(battle, owner_id="p2", controller_id="p2", zone=Zone.BATTLEFIELD)
    their_land = GameObject(land, owner_id="p2", controller_id="p2", zone=Zone.BATTLEFIELD)
    mine = GameObject(battle, owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.battlefield.extend([theirs, their_land, mine])
    offered = _offered(eng, "spell_or_nonland_permanent_you_dont_control")
    assert theirs.instance_id in offered
    assert their_land.instance_id not in offered and mine.instance_id not in offered
    assert {theirs.instance_id, mine.instance_id} <= _offered(eng, "spell_or_nonland_permanent")

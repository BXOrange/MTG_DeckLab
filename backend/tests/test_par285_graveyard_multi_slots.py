"""PAR-285: the graveyard pick's count/scope/tapped slots.

"exile 2 target cards from an opponent's graveyard" (fixed count with a scope word), "return up to 3 target land cards
from your graveyard to the battlefield tapped" (RULE 110.5b) and "exile all creature cards from target player's
graveyard" (a typed whole-graveyard exile). Tests run parser -> binder -> engine on the real cards' text."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.targeting import legal_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.test_mec118_opponent_choice import _engine, _put


def _real(name: str):
    card = CardDatabase(DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    return card


def _specs(name: str):
    result = parse_oracle(_real(name))
    assert result.modeled is True, name
    return [e for ab in result.specs if ab.effects for e in ab.effects]


def _land(i, zone=Zone.GRAVEYARD, owner="p1"):
    return Card(id=f"L{i}", name=f"Land{i}", type_line="Land", is_land=True)


def _creature(name):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True, power=2, toughness=2)


@pytest.mark.parametrize("name", ["Deadeye Tracker", "Lochmere Serpent", "Necromancer's Covenant",
                                  "Pull Through the Weft", "Vengeful Regrowth"])
def test_real_cards_are_modeled(name):
    _specs(name)


def test_parse_shapes():
    (exile,) = match_clause("exile 2 target cards from an opponent's graveyard")
    assert exile.params == {"target_kind": "opponent_graveyard_card", "count": 2}
    (own,) = match_clause("exile up to 2 target legendary creature cards from your graveyard")
    assert own.params["target_kind"] == "graveyard_legendary_creature" and own.params["optional"] is True
    (ret,) = match_clause("return up to 3 target land cards from your graveyard to the battlefield tapped")
    assert ret.params["tapped"] is True and ret.params["count"] == 3 and ret.params["destination"] == "battlefield"
    assert match_clause("return up to 2 target creature cards from your graveyard to your hand tapped") is None
    (mass,) = match_clause("exile all creature cards from target player's graveyard")
    assert mass.params == {"target_kind": "player", "card_type": "creature"}


def test_deadeye_tracker_offers_only_the_opponents_graveyard_and_exiles_two():
    eng = _engine()
    tracker = _put(eng, _real("Deadeye Tracker"), "p1")
    mine = _put(eng, _creature("Mine"), "p1", Zone.GRAVEYARD)
    theirs = [_put(eng, _creature(f"Theirs{i}"), "p2", Zone.GRAVEYARD) for i in range(3)]
    effect = build_effects([s for s in _specs("Deadeye Tracker") if s.type == "exile"], tracker)[0]
    offered = {o["instance_id"] for o in legal_targets(eng.state, "p1", effect.target_spec)}
    assert offered == {o.instance_id for o in theirs}
    effect.apply(GameContext(eng.state, eng.rules), theirs[:2])
    assert [o.zone for o in theirs] == [Zone.EXILE, Zone.EXILE, Zone.GRAVEYARD] and mine.zone == Zone.GRAVEYARD


def test_lochmere_serpent_takes_five():
    eng = _engine()
    serpent = _put(eng, _real("Lochmere Serpent"), "p1")
    theirs = [_put(eng, _creature(f"T{i}"), "p2", Zone.GRAVEYARD) for i in range(5)]
    effect = build_effects([s for s in _specs("Lochmere Serpent") if s.type == "exile"], serpent)[0]
    assert effect.target_spec.count == 5
    effect.apply(GameContext(eng.state, eng.rules), theirs)
    assert all(o.zone == Zone.EXILE for o in theirs)


def test_vengeful_regrowth_returns_lands_tapped():
    eng = _engine()
    spell = _put(eng, _real("Vengeful Regrowth"), "p1")
    lands = [_put(eng, _land(i), "p1", Zone.GRAVEYARD) for i in range(3)]
    bear = _put(eng, _creature("Bear"), "p1", Zone.GRAVEYARD)
    effect = build_effects(_specs("Vengeful Regrowth"), spell)[0]
    offered = {o["instance_id"] for o in legal_targets(eng.state, "p1", effect.target_spec)}
    assert offered == {o.instance_id for o in lands}  # never the creature card
    effect.apply(GameContext(eng.state, eng.rules), lands)
    eng.resolve_until_stable()
    assert all(o.zone == Zone.BATTLEFIELD and o.tapped for o in lands) and bear.zone == Zone.GRAVEYARD


def test_pull_through_the_weft_returns_nonland_to_hand_and_lands_tapped():
    eng = _engine()
    spell = _put(eng, _real("Pull Through the Weft"), "p1")
    bear = _put(eng, _creature("Bear"), "p1", Zone.GRAVEYARD)
    land = _put(eng, _land(1), "p1", Zone.GRAVEYARD)
    first, second = build_effects(_specs("Pull Through the Weft"), spell)[:2]
    ctx = GameContext(eng.state, eng.rules)
    first.apply(ctx, [bear])
    second.apply(ctx, [land])
    eng.resolve_until_stable()
    assert bear.zone == Zone.HAND and land.zone == Zone.BATTLEFIELD and land.tapped


def test_necromancers_covenant_exiles_only_creature_cards_and_pays_a_zombie_each():
    eng = _engine()
    covenant = _put(eng, _real("Necromancer's Covenant"), "p1")
    foe = eng.state.player_by_id("p2")
    bears = [_put(eng, _creature(f"B{i}"), "p2", Zone.GRAVEYARD) for i in range(2)]
    land = _put(eng, _land(1), "p2", Zone.GRAVEYARD)
    eng.rules._apply_effect_specs([e.to_dict() for e in _specs("Necromancer's Covenant")], covenant, [foe])
    eng.resolve_until_stable()
    assert all(b.zone == Zone.EXILE for b in bears) and land.zone == Zone.GRAVEYARD
    assert [o.name for o in eng.state.battlefield].count("Zombie") == 2

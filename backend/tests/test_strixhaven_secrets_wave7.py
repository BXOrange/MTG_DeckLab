"""Secrets of Strixhaven — playability batch, wave 7.

Wave 7: RULE 603.3f "1 or more [other] [nontoken] creatures [you control]
die" batch-death triggers. Originally a per-object DIES group trigger claimed
only with "This ability triggers only once each turn."; since PAR-119 (a) a
real RULE 603.2c batch (`EventType.EVENT_BATCH`), so the once-per-turn cards
keep their `limit` and the unlimited ones (Great Fierce Bee) are modeled too.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


@pytest.mark.parametrize("name", [
    "Morbid Opportunist", "Sengir Connoisseur", "Vraan, Executioner Thane",
    "Dramatic Finale", "Ghoulish Procession", "Homicide Investigator",
])
def test_batch_dies_once_per_turn_cards_modeled(name):
    c = _db().get_card(name)
    if c is None:
        pytest.skip(f"{name} not cached")
    r = parse_oracle(c)
    assert r.coverage != UNMODELED, (name, r.unclaimed)
    trig = [s for s in r.specs if s.trigger and s.trigger["event"] == "EVENT_BATCH"][0].trigger
    assert trig["batch"] == {"of": "DIES", "min": 1}
    assert trig["condition"]["subject"] == "group"
    assert trig["condition"]["filter"]["card_type"] == "creature"
    assert trig["limit"] is True


@pytest.mark.parametrize("name", ["Great Fierce Bee", "Vengeful Townsfolk"])
def test_unlimited_batch_dies_is_modeled_as_a_real_batch(name):
    c = _db().get_card(name)
    if c is None:
        pytest.skip(f"{name} not cached")
    r = parse_oracle(c)
    assert r.coverage != UNMODELED, r.unclaimed
    trig = [s for s in r.specs if s.trigger and s.trigger["event"] == "EVENT_BATCH"][0].trigger
    assert trig["batch"] == {"of": "DIES", "min": 1}
    assert "limit" not in trig


def test_morbid_opportunist_draws_once_per_turn_on_multiple_deaths():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    for i in range(5):
        p1.library.append(GameObject(Card(id=f"c{i}", name=f"C{i}", type_line="Forest",
                                          is_land=True), owner_id=p1.id, zone=Zone.LIBRARY))
    mo = GameObject(_db().get_card("Morbid Opportunist"), owner_id=p1.id, zone=Zone.BATTLEFIELD)
    mo.controller_id = p1.id
    mo.summoning_sick = False
    eng.state.add_to_battlefield(mo)
    bind_from_catalogue(mo)

    victims = []
    for i in range(2):
        v = GameObject(Card(id=f"v{i}", name=f"V{i}", type_line="Creature — Bear",
                            is_creature=True, power=1, toughness=1),
                       owner_id=p1.id, zone=Zone.BATTLEFIELD)
        v.controller_id = p1.id
        eng.state.add_to_battlefield(v)
        victims.append(v)

    before = len(p1.hand)
    for v in victims:
        eng.rules.destroy(v)
        eng.resolve_until_stable()
    assert len(p1.hand) - before == 1, "once per turn even though two creatures died"


def test_morbid_opportunist_does_not_fire_on_own_death():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    p1.library.append(GameObject(Card(id="c", name="C", type_line="Forest", is_land=True),
                                 owner_id=p1.id, zone=Zone.LIBRARY))
    mo = GameObject(_db().get_card("Morbid Opportunist"), owner_id=p1.id, zone=Zone.BATTLEFIELD)
    mo.controller_id = p1.id
    mo.summoning_sick = False
    eng.state.add_to_battlefield(mo)
    bind_from_catalogue(mo)
    before = len(p1.hand)
    eng.rules.destroy(mo)
    eng.resolve_until_stable()
    assert len(p1.hand) == before, "'other creatures' — its own death must not draw"

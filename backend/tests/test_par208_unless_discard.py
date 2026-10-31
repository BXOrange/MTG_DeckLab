"""PAR-208 slice 2: "<sacrifice/exile> it unless you discard a <type> card [at random]" and "discard N cards unless you
discard an instant or sorcery / a basic land card" -- parsed and executed in the real engine (RULE 118.12, 701.8)."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.costs import discard_filter_matches
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.game import creature, land, make_engine

_DB = CardDatabase(DB_PATH)


def _named(name: str) -> Card:
    card = _DB.get_card(name)
    assert card is not None, name
    return card


def _instant(name: str = "Shock") -> Card:
    return Card(id=name, name=name, type_line="Instant", is_instant=True)


def _sorcery(name: str = "Divination") -> Card:
    return Card(id=name, name=name, type_line="Sorcery", is_sorcery=True)


def _hand(eng, cards: list[Card]) -> list[GameObject]:
    out = []
    for card in cards:
        obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
        eng.state.player_by_id("p1").hand.append(obj)
        out.append(obj)
    return out


def _enter(eng, name: str) -> GameObject:
    obj = GameObject(_named(name), owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id="p1", object=obj.name, instance_id=obj.instance_id,
        object_types=sorted(obj.type_words),
    ))
    eng.resolve_until_stable()
    return obj


def _engine():
    eng = make_engine([creature(f"Lib {i}") for i in range(10)], [creature("Opp")], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _answer(eng, option: str) -> None:
    choice = eng.state.pending_choice
    assert choice is not None, "expected an open choice"
    ids = [o["id"] for o in choice["options"]]
    assert option in ids, (option, ids)
    eng.resolve_pending_choice(option)
    eng.resolve_until_stable()


def _pay_with(eng, card_obj: GameObject) -> None:
    """Accept the unless-payment, then name the discarded card."""
    choice = eng.state.pending_choice
    ids = [o["id"] for o in choice["options"]]
    if "pay" in ids:
        _answer(eng, "pay")
    elif "do" in ids:
        _answer(eng, "do")
    if eng.state.pending_choice is not None:
        _answer(eng, str(card_obj.instance_id))


@pytest.mark.parametrize("name", [
    "Fallow Wurm", "Thundering Wurm", "Hidden Horror", "Mercenary Knight", "Drekavac", "Body Snatcher",
    "Balduvian Horde", "Minotaur Explorer", "Pillaging Horde", "Cursed Monstrosity", "Practical Research",
    "Thirst for Discovery",
])
def test_claimed_cards_are_modeled(name):
    assert parse_oracle(_named(name)).coverage == MODELED


def test_fallow_wurm_stays_when_a_land_card_is_discarded():
    eng = _engine()
    [forest, bolt] = _hand(eng, [land(), _instant()])
    wurm = _enter(eng, "Fallow Wurm")
    _pay_with(eng, forest)
    assert wurm.zone is Zone.BATTLEFIELD and forest.zone is Zone.GRAVEYARD and bolt.zone is Zone.HAND


def test_fallow_wurm_is_sacrificed_when_the_player_declines():
    eng = _engine()
    _hand(eng, [land()])
    wurm = _enter(eng, "Fallow Wurm")
    _answer(eng, "decline")
    assert wurm.zone is Zone.GRAVEYARD


def test_fallow_wurm_is_sacrificed_without_a_land_card_in_hand():
    eng = _engine()
    _hand(eng, [_instant()])
    wurm = _enter(eng, "Fallow Wurm")
    assert wurm.zone is Zone.GRAVEYARD  # a payment nobody can make is not offered


def test_drekavac_only_accepts_a_noncreature_card():
    eng = _engine()
    [bear, bolt] = _hand(eng, [creature("Bear"), _instant()])
    drek = _enter(eng, "Drekavac")
    choice = eng.state.pending_choice
    if choice is not None and "pay" in [o["id"] for o in choice["options"]]:
        _answer(eng, "pay")
    pool = [o["id"] for o in (eng.state.pending_choice or {}).get("options", [])]
    assert str(bear.instance_id) not in pool  # RULE 205.2: a creature card is not a noncreature card
    if pool:
        _answer(eng, str(bolt.instance_id))
    assert drek.zone is Zone.BATTLEFIELD and bolt.zone is Zone.GRAVEYARD and bear.zone is Zone.HAND


def test_balduvian_horde_discards_at_random_and_stays():
    eng = _engine()
    cards = _hand(eng, [creature("A"), creature("B")])
    horde = _enter(eng, "Balduvian Horde")
    choice = eng.state.pending_choice
    if choice is not None:
        _answer(eng, "pay")
    assert horde.zone is Zone.BATTLEFIELD
    assert sum(c.zone is Zone.GRAVEYARD for c in cards) == 1  # exactly one, nothing was chosen


def test_body_snatcher_is_exiled_without_a_creature_card_to_discard():
    eng = _engine()
    _hand(eng, [_instant(), land()])
    snatcher = _enter(eng, "Body Snatcher")
    assert snatcher.zone is Zone.EXILE


def test_body_snatcher_stays_when_a_creature_card_is_discarded():
    eng = _engine()
    [bear] = _hand(eng, [creature("Bear")])
    snatcher = _enter(eng, "Body Snatcher")
    _pay_with(eng, bear)
    assert snatcher.zone is Zone.BATTLEFIELD and bear.zone is Zone.GRAVEYARD


def _cast(eng, name: str) -> None:
    obj = GameObject(_named(name), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1 = eng.state.player_by_id("p1")
    p1.hand.append(obj)
    p1.mana_pool.add_many({"U": 3, "R": 3, "G": 3, "C": 3})
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()


def test_practical_research_keeps_the_hand_when_an_instant_or_sorcery_is_discarded():
    eng = _engine()
    [bolt, bear] = _hand(eng, [_instant(), creature("Bear")])
    _cast(eng, "Practical Research")
    # 4 cards drawn, then "discard 2 cards unless you discard an instant or sorcery card"
    choice = eng.state.pending_choice
    assert choice is not None
    pool = {o["id"] for o in choice["options"]}
    assert str(bolt.instance_id) in pool and str(bear.instance_id) not in pool
    _answer(eng, str(bolt.instance_id))
    assert bolt.zone is Zone.GRAVEYARD and bear.zone is Zone.HAND
    assert len(eng.state.player_by_id("p1").graveyard) >= 1


def test_practical_research_discards_two_when_declined():
    eng = _engine()
    _hand(eng, [_instant()])
    p1 = eng.state.player_by_id("p1")
    _cast(eng, "Practical Research")
    _answer(eng, "decline")
    while eng.state.pending_choice is not None:
        _answer(eng, eng.state.pending_choice["options"][0]["id"])
    assert len([o for o in p1.graveyard if o.name != "Practical Research"]) == 2  # the spell itself lands there too


def test_thirst_for_discovery_wants_a_basic_land_not_any_land():
    eng = _engine()
    nonbasic = Card(id="Tavern", name="Tavern", type_line="Land", is_land=True)
    [tavern, forest] = _hand(eng, [nonbasic, land()])
    _cast(eng, "Thirst for Discovery")
    choice = eng.state.pending_choice
    pool = {o["id"] for o in choice["options"]}
    assert str(forest.instance_id) in pool and str(tavern.instance_id) not in pool


@pytest.mark.parametrize("word,line,expected", [
    ("land", "Basic Land — Forest", True),
    ("noncreature", "Instant", True),
    ("noncreature", "Artifact Creature — Golem", False),
    ("instant_or_sorcery", "Sorcery", True),
    ("instant_or_sorcery", "Creature — Bear", False),
])
def test_discard_filter_matches(word, line, expected):
    assert discard_filter_matches(word, line) is expected

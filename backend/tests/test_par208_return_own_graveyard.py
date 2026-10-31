"""PAR-208 slice 2: untargeted "return [up to N] <type> card(s) from your graveyard to your hand" (the resolving
player's own pick) and "you may X. Then Y" (only X optional), executed in the real engine."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.game import creature, land, make_engine

_DB = CardDatabase(DB_PATH)


def _named(name: str) -> Card:
    card = _DB.get_card(name)
    assert card is not None, name
    return card


def _engine():
    eng = make_engine([land(f"Lib {i}") for i in range(10)], [creature("Opp")], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _grave(eng, cards: list[Card]) -> list[GameObject]:
    out = []
    for card in cards:
        obj = GameObject(card, owner_id="p1", zone=Zone.GRAVEYARD)
        eng.state.player_by_id("p1").graveyard.append(obj)
        out.append(obj)
    return out


def _cast(eng, name: str) -> None:
    obj = GameObject(_named(name), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1 = eng.state.player_by_id("p1")
    p1.hand.append(obj)
    p1.mana_pool.add_many({"U": 4, "B": 4, "G": 4, "R": 4, "W": 4, "C": 4})
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()


def _drive(eng, pick=None, accept: bool = True) -> None:
    for _ in range(12):
        choice = eng.state.pending_choice
        if choice is None:
            return
        ids = [o["id"] for o in choice["options"]]
        if "yes" in ids:  # the optional composite's prompt
            eng.resolve_pending_choice("yes" if accept else "decline")
        elif pick and any(str(p.instance_id) in ids for p in pick):
            eng.resolve_pending_choice(next(str(p.instance_id) for p in pick if str(p.instance_id) in ids))
        else:
            eng.resolve_pending_choice(next(i for i in ids if i != "decline"))
        eng.resolve_until_stable()


@pytest.mark.parametrize("name", [
    "Another Chance", "Druidic Ritual", "Carrion Cruiser", "Fell Gravship", "Sudden Reclamation",
    "Ashcoat of the Shadow Swarm", "Bond of Insight", "Overlord of the Balemurk",
])
def test_claimed_cards_are_modeled(name):
    assert parse_oracle(_named(name)).coverage == MODELED


def test_another_chance_returns_up_to_two_creature_cards_after_the_optional_mill():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    a, b, c = _grave(eng, [creature("A"), creature("B"), creature("C")])
    _cast(eng, "Another Chance")
    _drive(eng, pick=[a, b])
    assert a.zone is Zone.HAND and b.zone is Zone.HAND and c.zone is Zone.GRAVEYARD
    assert len(p1.library) == 8  # milled two


def test_another_chance_still_returns_cards_when_the_mill_is_declined():
    # "You may mill two cards. THEN return ..." -- only the mill is optional (RULE 608.2c).
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    a, = _grave(eng, [creature("A")])
    _cast(eng, "Another Chance")
    _drive(eng, pick=[a], accept=False)
    assert a.zone is Zone.HAND and len(p1.library) == 10


def test_sudden_reclamation_returns_one_creature_and_one_land():
    eng = _engine()
    bear, forest, other = _grave(eng, [creature("Bear"), land("Forest", "Forest"), creature("Other")])
    _cast(eng, "Sudden Reclamation")
    _drive(eng, pick=[bear, forest])
    assert bear.zone is Zone.HAND and forest.zone is Zone.HAND and other.zone is Zone.GRAVEYARD


def test_carrion_cruiser_takes_a_creature_or_vehicle_card():
    spec = match_clause("return a creature or vehicle card from your graveyard to your hand")
    assert spec[0].params["permanent_filter"] == {"any_of": [{"card_type": "creature"}, {"subtype": "vehicle"}]}


@pytest.mark.parametrize("name,eligible", [
    ("Inspiration from Beyond", Card(id="spell", name="Spell", type_line="Instant", is_instant=True)),
    ("Takenuma, Abandoned Mire", creature("Bear")),
    ("Under the Skin", land()),
    ("Vanille, Cheerful l'Cie", land()),
])
def test_changed_existing_return_specs_keep_their_pool_and_execute(name, eligible):
    eng = _engine()
    source = GameObject(_named(name), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(source)
    eng.state.add_to_battlefield(source)
    result = parse_oracle(source.card)
    node = next(e for s in result.specs for e in s.effects if e.type == "choose_objects")
    good, bad = _grave(eng, [eligible, Card(id="bad", name="Bad", type_line="Sorcery", is_sorcery=True)
                           if name != "Inspiration from Beyond" else creature("Bad")])
    for effect in build_effects([node], source):
        effect.apply(eng.rules.context)
    _drive(eng, pick=[good])
    assert good.zone is Zone.HAND and bad.zone is Zone.GRAVEYARD


def test_summon_undead_reanimates_even_when_the_mill_is_declined():
    eng = _engine()
    bear, = _grave(eng, [creature("Bear")])
    before = len(eng.state.player_by_id("p1").library)
    _cast(eng, "Summon Undead")
    _drive(eng, pick=[bear], accept=False)
    assert bear.zone is Zone.BATTLEFIELD
    assert len(eng.state.player_by_id("p1").library) == before


def test_gallifrey_stands_checks_victory_after_declining_the_doctor():
    eng = _engine()
    source = GameObject(_named("Gallifrey Stands"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(source)
    eng.state.add_to_battlefield(source)
    for i in range(13):
        obj = GameObject(creature(f"Doctor {i}", type_line="Creature — Doctor"), owner_id="p1", zone=Zone.BATTLEFIELD)
        eng.state.add_to_battlefield(obj)
    doctor = GameObject(creature("Hand Doctor", type_line="Creature — Doctor"), owner_id="p1", zone=Zone.HAND)
    eng.state.player_by_id("p1").hand.append(doctor)
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", player_id="p1", controller_id="p1"))
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and any(o["id"] == "decline" for o in choice["options"])
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    assert doctor.zone is Zone.HAND
    assert eng.state.player_by_id("p2").has_lost


@pytest.mark.parametrize("clause", [
    "return target creature card from your graveyard to your hand",  # a RULE 115 target is another row's
    "return a creature card from an opponent's graveyard to your hand",
    "return a creature card from your graveyard to the battlefield",
])
def test_near_misses_stay_with_their_own_rows(clause):
    specs = match_clause(clause)
    assert specs is None or specs[0].type != "choose_objects"

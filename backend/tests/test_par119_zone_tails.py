"""PAR-119 (a) — "…leave(s) the battlefield without dying" / "…enter without being played".

LEAVES_BATTLEFIELD now stamps where the permanent went (``to_zone``), so "without dying"
is "not to a graveyard"; a played land's ENTERS_BATTLEFIELD is stamped ``played`` (RULE
305.1), so "without being played" is every other way onto the battlefield.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase

WITHOUT_DYING = ("Whenever another creature you control leaves the battlefield without dying, "
                 "you gain 1 life.")
NOT_PLAYED = ("Whenever one or more lands enter under an opponent's control without being "
              "played, you gain 1 life.")


def _engine():
    engine = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    engine.state.current_step = "main1"
    return engine


def _bf(state, card, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _bear(state, owner="p1"):
    return _bf(state, Card(id="Bear", name="Bear", type_line="Creature — Bear", is_creature=True,
                           power=2, toughness=2), owner)


def _listener(state, oracle):
    card = Card(id="Listener", name="Listener", type_line="Enchantment", oracle_text=oracle)
    assert parse_oracle(card).modeled, parse_oracle(card).unclaimed
    return _bf(state, card)


def _life(engine):
    return engine.state.player_by_id("p1").life


@pytest.mark.parametrize("move, expected", [
    ("return_to_hand", 21), ("exile", 21), ("shuffle_into_library", 21), ("destroy", 20),
])
def test_without_dying_is_any_departure_but_the_graveyard(move, expected):
    engine = _engine()
    _listener(engine.state, WITHOUT_DYING)
    bear = _bear(engine.state)
    getattr(engine.rules, move)(bear)
    engine.resolve_until_stable()
    assert _life(engine) == expected


def test_a_played_land_is_not_put_onto_the_battlefield():
    engine = _engine()
    _listener(engine.state, NOT_PLAYED)
    engine.state.active_player_index = 1
    them = engine.state.player_by_id("p2")
    land = GameObject(Card(id="Island", name="Island", type_line="Basic Land — Island",
                           is_land=True), owner_id="p2", zone=Zone.HAND)
    them.hand.append(land)
    engine.play_land(them, land)
    engine.resolve_until_stable()
    assert _life(engine) == 20


def test_a_land_put_onto_the_battlefield_counts():
    engine = _engine()
    _listener(engine.state, NOT_PLAYED)
    engine.state.active_player_index = 1
    them = engine.state.player_by_id("p2")
    them.library.append(GameObject(Card(id="Island", name="Island", type_line="Basic Land — Island",
                                        is_land=True), owner_id="p2", zone=Zone.LIBRARY))
    card = Card(id="Ramp", name="Ramp", type_line="Sorcery", is_sorcery=True,
                oracle_text="Search your library for a basic land card, put it onto the "
                            "battlefield, then shuffle.")
    assert parse_oracle(card).modeled
    spell = GameObject(card, owner_id="p2", zone=Zone.HAND)
    bind_from_catalogue(spell)
    them.hand.append(spell)
    engine.cast_spell(them, spell)
    engine.resolve_until_stable()
    if engine.state.pending_choice:
        option = next(o for o in engine.state.pending_choice["options"] if o.get("instance_id"))
        engine.rules.resolve_choice(str(option["instance_id"]))
        engine.resolve_until_stable()
    assert any(o.name == "Island" for o in engine.state.battlefield)
    assert _life(engine) == 21


@pytest.mark.full_cache
@pytest.mark.parametrize("name", ["Dour Port-Mage", "Imperial Cosmographer", "Three Tree Scribe"])
def test_real_cards_are_modeled(name):
    assert parse_oracle(CardDatabase(DB_PATH).get_card(name)).modeled


# ---------------------------------------------------------------------------
# Legacy-row migration: "is put into **your** graveyard from the battlefield"
# ---------------------------------------------------------------------------

SCRAPHEAP = ("Whenever an artifact is put into your graveyard from the battlefield, "
             "you gain 1 life.")


@pytest.mark.parametrize("owner, expected", [("p1", 21), ("p2", 20)])
def test_your_graveyard_is_the_owners(owner, expected):
    """The retired row dropped "your", so an opponent's artifact counted too."""
    engine = _engine()
    _listener(engine.state, SCRAPHEAP)
    relic = _bf(engine.state, Card(id="Relic", name="Relic", type_line="Artifact"), owner)
    engine.rules.destroy(relic)
    engine.resolve_until_stable()
    assert _life(engine) == expected


@pytest.mark.parametrize("cond, expected", [
    ("another elf you control enters",
     {"subject": "group", "controller": "you", "other": True, "subtypes": ["elf"],
      "nontoken": False}),
    ("~ or another creature dies",
     {"subject": "self_or_group", "controller": "any", "other": True, "type": "creature"}),
    ("another permanent you control enters",
     {"subject": "group", "controller": "you", "other": True, "type": "permanent"}),
    ("a green creature dies",
     {"subject": "group", "controller": "any", "other": False, "type": "creature", "color": "G"}),
    ("a non-angel creature you control dies",
     {"subject": "group", "controller": "you", "other": False, "type": "creature",
      "excluded_subtypes": ["angel"]}),
    # Richer than the flat keys can say → stays in the composed ``filter`` form.
    ("another nontoken creature you control dies", None),
    ("a creature with flying you control attacks", None),
])
def test_legacy_group_condition(cond, expected):
    from mtg_analyzer.parser.oracle.catalogue.object_trigger_head import legacy_group_condition

    got = legacy_group_condition(cond)
    assert (got[1] if got else None) == expected

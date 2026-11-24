"""PAR-292 M11: the "look at / reveal the top N, take some, rest on the bottom" digs.

Per-item numeric bounds ("a creature card with power 2 or less"), plural unions ("up to two instant and/or sorcery
cards", "all creature and land cards"), the one-of-each pick ("a creature card and/or a land card", RULE 205.2a), the
"of the chosen type" kind, the on-top pick, and the "in any order" bottom pile (RULE 401.4: the player's own order,
unlike "in a random order"). Claimed cards run on a real engine; the bystanders (cards not matching the quality) must
stay in the library and go to its bottom, and a "look at" must not reveal them (RULE 701.20).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.dig import parse_criteria
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.models.game.game_state import EventType

from tests.test_par144_dig_family import _card, _engine, _stock


def _modeled(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.parser.oracle import parse_oracle
    from mtg_analyzer.services.card_database import CardDatabase
    return parse_oracle(CardDatabase(DB_PATH).get_card(name)).modeled


@pytest.mark.parametrize("name", [
    "Militia Bugler", "Squad Rallier", "Star Charter", "Living Phone", "Mayael the Anima", "Gift of the Gargantuan",
    "Uncovered Clues", "Lair Delve", "Torsten, Founder of Benalia", "Tazri, Beacon of Unity", "Benefaction of Rhonas",
    "In the Presence of Ages", "Pieces of the Puzzle", "Relentless Pursuit", "Icon of Ancestry", "Brass Herald",
    "Silhana Wayfinder",
])
def test_claimed_cards_are_modeled(name):
    assert _modeled(name)


# --- parse ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("phrase", "expected"), [
    ("a creature card with power 2 or less", {"type": "creature", "max_power": 2}),
    ("a creature card with power 5 or greater", {"type": "creature", "min_power": 5}),
    ("a creature card with toughness 1 or less", {"type": "creature", "max_toughness": 1}),
    ("an artifact card with mana value 3 or less", {"type": "artifact", "max_mana_value": 3}),
    ("a creature card of the chosen type", {"all_types": ["creature", "chosen_type"]}),
])
def test_item_qualifiers(phrase, expected):
    assert parse_criteria(phrase) == expected


def test_and_or_unions_need_a_plural_quantity():
    assert parse_criteria("instant and/or sorcery cards", union_and=True) == {"type": ["instant", "sorcery"]}
    assert parse_criteria("creature and land cards", union_and=True) == {"type": ["creature", "land"]}
    assert parse_criteria("cleric, rogue, and/or ally cards", union_and=True) == {"type": ["cleric", "rogue", "ally"]}
    assert parse_criteria("instant and/or sorcery cards") is None
    assert parse_criteria("creature and land cards") is None


_LOOK4 = "look at the top 4 cards of your library. "
_REST_ANY = " put the rest on the bottom of your library in any order."


@pytest.mark.parametrize("text", [
    # the "power" qualifier must be a number bound, not a stat comparison
    _LOOK4 + "you may reveal a creature card with power equal to its toughness from among them and put it into your hand."
    " put the rest on the bottom of your library in a random order.",
    # "a creature card and/or a land card" with a subtype word is not a card-type pair
    _LOOK4 + "you may reveal an elf card and/or a land card from among them and put the revealed cards into your hand."
    + _REST_ANY,
    # one pick may not be a union spelled with "and"
    _LOOK4 + "you may reveal a creature and land card from among them and put it into your hand." + _REST_ANY,
])
def test_near_misses_stay_unclaimed(text):
    assert match_clause(text) is None


# --- execution --------------------------------------------------------------------------------------------------

def _resolve(eng, player, oracle_text, chosen_type=None):
    spell = GameObject(
        _card("Dig Spell", "Sorcery", cost="", cmc=0, oracle_text=oracle_text), owner_id="p1", zone=Zone.HAND,
    )
    bind_from_catalogue(spell)
    spell.chosen_type = chosen_type
    player.add_to_zone(spell, Zone.HAND)
    eng.rules.cast_spell(player, spell)
    eng.resolve_until_stable()


def _offered(eng):
    return [o["label"] for o in eng.state.pending_choice["options"] if "instance_id" in o]


def _take(eng, *names):
    for name in names:
        option = next(o for o in eng.state.pending_choice["options"] if o.get("label") == name)
        eng.rules.resolve_choice(option["instance_id"])
        eng.resolve_until_stable()


def _top_down(player):
    return [o.name for o in reversed(player.library)]


def _stock_deep(player, top, deep="Deep"):
    """A library whose bottom is one ``deep`` card under the ``top`` cards (top first)."""
    _stock(player, *top, _card(deep, "Sorcery", cost="", cmc=0))


def _creature(name, power, cmc=2):
    return _card(name, "Creature — Bear", cmc=cmc, power=power, toughness=2)


def test_power_bound_offers_only_small_creatures_and_the_rest_goes_to_the_bottom():
    eng, p1 = _engine()
    big, small, other = _creature("Big", 3), _creature("Small", 2), _creature("Other", 1)
    land = _card("Plain Land", "Land", cost="", cmc=0)
    _stock_deep(p1, [big, small, land, other])
    _resolve(eng, p1,
             _LOOK4 + "you may reveal a creature card with power 2 or less from among them and put it into your hand."
             " put the rest on the bottom of your library in a random order.")
    assert sorted(_offered(eng)) == ["Other", "Small"]  # Big (power 3) and the land are not offered
    _take(eng, "Small")
    assert [o.name for o in p1.hand] == ["Small"]
    assert sorted(o.name for o in p1.library[:3]) == ["Big", "Other", "Plain Land"]
    assert p1.library[3].name == "Deep"  # the rest went under the untouched card


def test_a_look_at_reveals_nothing_to_the_opponent():
    eng, p1 = _engine()
    _stock_deep(p1, [_creature("Small", 1), _creature("Small2", 1), _card("Bolt", "Instant"), _card("Opt", "Instant")])
    _resolve(eng, p1,
             _LOOK4 + "you may reveal a creature card with power 2 or less from among them and put it into your hand."
             " put the rest on the bottom of your library in a random order.")
    _take(eng, "Small")
    # the chosen card is revealed (RULE 701.20: "reveal a creature card"); the unchosen cards never are
    revealed = {e.get("object") for e in eng.state.event_log if e.type == EventType.REVEAL}
    assert "Small" in revealed and "Small2" not in revealed and "Deep" not in revealed


def test_declining_still_bottoms_every_looked_at_card():
    eng, p1 = _engine()
    _stock_deep(p1, [_creature("Small", 1), _creature("Small2", 1), _card("Bolt", "Instant"), _card("Opt", "Instant")])
    _resolve(eng, p1,
             _LOOK4 + "you may reveal a creature card with power 2 or less from among them and put it into your hand."
             " put the rest on the bottom of your library in a random order.")
    eng.rules.resolve_choice(None)
    eng.resolve_until_stable()
    assert not p1.hand
    assert sorted(o.name for o in p1.library[:4]) == ["Bolt", "Opt", "Small", "Small2"]
    assert p1.library[4].name == "Deep"


def test_min_power_onto_the_battlefield_with_an_any_order_bottom():
    eng, p1 = _engine()
    giant, tiny = _creature("Giant", 5, cmc=5), _creature("Tiny", 1)
    land = _card("Plain Land", "Land", cost="", cmc=0)
    _stock_deep(p1, [tiny, giant, land])
    _resolve(eng, p1,
             "look at the top 3 cards of your library. you may put a creature card with power 5 or greater from among"
             " them onto the battlefield. put the rest on the bottom of your library in any order.")
    assert _offered(eng) == ["Giant"]
    _take(eng, "Giant")
    assert [o.name for o in eng.state.battlefield if o.name == "Giant"] == ["Giant"]
    # RULE 401.4: "any order" is the player's own ordering: a pending choice over exactly the unchosen cards
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "library_bottom"
    labels = sorted(o["label"] for o in choice["options"] if o.get("label"))
    assert [name for name in labels if name in ("Tiny", "Plain Land")] == ["Plain Land", "Tiny"]
    assert "Deep" not in labels  # a card that was not looked at is not part of the pile


def test_union_up_to_two_takes_both_kinds_and_leaves_the_others():
    eng, p1 = _engine()
    bolt = _card("Bolt", "Instant", cost="{R}", cmc=1)
    ponder = _card("Ponder", "Sorcery", cost="{U}", cmc=1)
    bear, land = _creature("Bear", 2), _card("Plain Land", "Land", cost="", cmc=0)
    _stock_deep(p1, [bolt, bear, ponder, land])
    _resolve(eng, p1,
             _LOOK4 + "you may reveal up to 2 instant and/or sorcery cards from among them and put the revealed cards"
             " into your hand. put the rest on the bottom of your library in a random order.")
    assert sorted(_offered(eng)) == ["Bolt", "Ponder"]
    _take(eng, "Bolt", "Ponder")
    assert sorted(o.name for o in p1.hand) == ["Bolt", "Ponder"]
    assert sorted(o.name for o in p1.library[:2]) == ["Bear", "Plain Land"]


def test_all_creature_and_land_cards_are_taken_without_a_choice():
    eng, p1 = _engine()
    _stock_deep(p1, [_creature("Bear", 2), _card("Plain Land", "Land", cost="", cmc=0), _card("Bolt", "Instant")])
    _resolve(eng, p1,
             "reveal the top 3 cards of your library. put all creature and land cards revealed this way into your hand"
             " and the rest on the bottom of your library in a random order.")
    assert sorted(o.name for o in p1.hand) == ["Bear", "Plain Land"]
    assert [o.name for o in p1.library] == ["Bolt", "Deep"]


def test_one_of_each_type_cannot_take_two_creatures():
    eng, p1 = _engine()
    a, b = _creature("Bear A", 2), _creature("Bear B", 2)
    land = _card("Plain Land", "Land", cost="", cmc=0)
    _stock_deep(p1, [a, b, land])
    _resolve(eng, p1,
             _LOOK4 + "you may reveal a creature card and/or a land card from among them and put the revealed cards"
             " into your hand. put the rest on the bottom of your library in a random order.")
    _take(eng, "Bear A")
    assert "Bear B" not in _offered(eng)  # the second pick must be the other type (RULE 205.2a)
    assert _offered(eng) == ["Plain Land"]
    _take(eng, "Plain Land")
    assert sorted(o.name for o in p1.hand) == ["Bear A", "Plain Land"]
    assert [o.name for o in p1.library if o.name == "Bear B"] == ["Bear B"]


def test_on_top_pick_keeps_the_card_on_top_and_bottoms_the_rest():
    eng, p1 = _engine()
    _stock_deep(p1, [_creature("Bear", 2), _card("Bolt", "Instant"), _card("Plain Land", "Land", cost="", cmc=0)])
    _resolve(eng, p1,
             "look at the top 3 cards of your library. you may reveal a creature or land card from among them and put it"
             " on top of your library. put the rest on the bottom of your library in a random order.")
    _take(eng, "Bear")
    assert p1.library[-1].name == "Bear"
    assert sorted(o.name for o in p1.library[:2]) == ["Bolt", "Plain Land"]
    assert p1.library[2].name == "Deep"


def test_chosen_type_dig_offers_only_that_type():
    eng, p1 = _engine()
    elf = _card("Elf", "Creature — Elf", cmc=1, power=1, toughness=1)
    goblin = _card("Goblin", "Creature — Goblin", cmc=1, power=1, toughness=1)
    _stock_deep(p1, [elf, goblin])
    _resolve(eng, p1,
             "look at the top 2 cards of your library. you may reveal a creature card of the chosen type from among them"
             " and put it into your hand. put the rest on the bottom of your library in a random order.",
             chosen_type="Elf")
    assert _offered(eng) == ["Elf"]
    _take(eng, "Elf")
    assert [o.name for o in p1.hand] == ["Elf"]
    assert [o.name for o in p1.library] == ["Goblin", "Deep"]


def test_any_order_bottom_places_the_pile_in_the_players_chosen_order():
    eng, p1 = _engine()
    giant, tiny = _creature("Giant", 5, cmc=5), _creature("Tiny", 1)
    land = _card("Plain Land", "Land", cost="", cmc=0)
    _stock_deep(p1, [tiny, giant, land])
    _resolve(eng, p1,
             "look at the top 3 cards of your library. you may put a creature card with power 5 or greater from among"
             " them onto the battlefield. put the rest on the bottom of your library in any order.")
    _take(eng, "Giant")
    choice = eng.state.pending_choice
    by_label = {o["label"]: o["id"] for o in choice["options"] if o.get("label") in ("Tiny", "Plain Land")}
    eng.rules.resolve_choice(str(by_label["Plain Land"]))  # first pick = topmost of the pile
    if eng.state.pending_choice is not None:  # (the last card of an ordering is forced)
        eng.rules.resolve_choice(str(by_label["Tiny"]))
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None
    # library is bottom-first: the pile sits under Deep, its topmost card (Plain Land) right under Deep
    assert [o.name for o in p1.library] == ["Tiny", "Plain Land", "Deep"]

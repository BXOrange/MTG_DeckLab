"""PAR-144 — the "dig" family: "Look at/Reveal the top N cards of your library. You may reveal a
`<kind>` card from among them and put it into your hand/onto the battlefield. Put the rest on the
bottom of your library / into your graveyard." (`parser/oracle/catalogue/dig.py`).

Parse tests pin the criteria vocabulary and what stays unclaimed; execute tests resolve real spells
against a real engine (a parse-only test would not have caught a dropped criteria param).

Reference: parser/oracle/catalogue/dig.py, game/effects/returns_graveyards.py
(`InspectTopChooseEffect`), game/rules/search_mixin.py (`inspect_top_n_choose`),
models/cards/card_query.py.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards import card_query
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.dig import parse_criteria
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause


def _card(name, type_line="Creature — Bear", cost="{1}{G}", cmc=2, **kw):
    lowered = type_line.lower()
    for flag in ("instant", "sorcery", "land", "creature"):
        kw.setdefault(f"is_{flag}", flag in lowered)
    if kw.get("is_creature"):
        kw.setdefault("power", 2)
        kw.setdefault("toughness", 2)
    return Card(id=name, name=name, type_line=type_line, mana_cost_string=cost,
                converted_mana_cost=cmc, **kw)


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng, eng.state.players[0]


def _stock(player, *cards):
    """Library from the *top* down: ``cards[0]`` is the top card (``library[-1]``)."""
    for card in reversed(cards):
        player.library.append(GameObject(card, owner_id="p1", zone=Zone.LIBRARY))


def _cast(eng, player, oracle_text):
    spell_card = _card("Dig Spell", "Sorcery", cost="", cmc=0, oracle_text=oracle_text)
    spell = GameObject(spell_card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    player.add_to_zone(spell, Zone.HAND)
    eng.rules.cast_spell(player, spell)
    eng.resolve_until_stable()


def _answer(eng, names_to_take):
    """Answer the pending pick(s): take the offered cards named in ``names_to_take``, then stop."""
    taken = 0
    while eng.state.pending_choice is not None:
        offered = [o for o in eng.state.pending_choice["options"] if "instance_id" in o]
        wanted = [o for o in offered if o["label"] in names_to_take]
        if not wanted:
            eng.rules.resolve_choice(None)
            break
        eng.rules.resolve_choice(wanted[0]["instance_id"])
        taken += 1
        eng.resolve_until_stable()
    return taken


def _names(zone):
    return [o.name for o in zone]


# ---------------------------------------------------------------------------
# Parse: the criteria vocabulary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("phrase", "expected"), [
    ("a creature card", {"type": "creature"}),
    ("a creature or land card", {"type": ["creature", "land"]}),
    ("an elf, warrior, or tyvar card", {"type": ["elf", "warrior", "tyvar"]}),
    ("a dragon creature card", {"all_types": ["dragon", "creature"]}),
    ("a historic card", {"type": ["artifact", "legendary", "saga"]}),
    ("a nonland permanent card", {"type": ["artifact", "creature", "enchantment", "planeswalker", "battle"]}),
    ("a white card", {"color": ["W"]}),
    ("a colorless card", {"color": ["colorless"]}),
    ("a card", {}),
    ("creature cards with mana value 3 or less", {"type": "creature", "max_mana_value": 3}),
    ("an artifact or enchantment card with mana value 3 or less",
     {"type": ["artifact", "enchantment"], "max_mana_value": 3}),
    ("a land card or a card with {x} in its mana cost", {"or": [{"type": "land"}, {"has_x_cost": True}]}),
    ("a knight, aura, equipment, or legendary artifact card",
     {"or": [{"type": "knight"}, {"type": "aura"}, {"type": "equipment"},
             {"all_types": ["legendary", "artifact"]}]}),
])
def test_dig_criteria_vocabulary(phrase, expected):
    assert parse_criteria(phrase) == expected


@pytest.mark.parametrize("phrase", [
    "a creature card with mana value x or less",   # an announced-X magnitude: refused
    "a creature card and/or an enchantment card",  # two separate picks
    "a multicolored card",                         # adjective outside the vocabulary
    "a creature card with power 3 or greater",     # qualifier outside the vocabulary
])
def test_dig_criteria_refuses_what_it_cannot_express(phrase):
    assert parse_criteria(phrase) is None


def test_whole_word_type_match_does_not_confuse_orc_with_sorcery():
    sorcery = _card("Divination", "Sorcery", cost="{2}{U}", cmc=3)
    orc = _card("Orc Grunt", "Creature — Orc Warrior")
    island = _card("Island", "Basic Land — Island", cost="", cmc=0)
    assert not card_query.matches(sorcery, {"type": "orc"})
    assert card_query.matches(orc, {"type": "orc"})
    assert card_query.matches(orc, {"all_types": ["orc", "creature"]})
    assert card_query.matches(island, {"type": "land"})
    assert card_query.matches(island, {"type": "basic land"})


# ---------------------------------------------------------------------------
# Parse: the clause
# ---------------------------------------------------------------------------

_BOTTOM = "put the rest on the bottom of your library in a random order"


def test_dig_clause_to_hand_with_bottom_rest():
    specs = match_clause(
        "look at the top 5 cards of your library. you may reveal a historic card from among them "
        f"and put it into your hand. {_BOTTOM}"
    )
    assert [s.type for s in specs] == ["inspect_top_choose"]
    assert specs[0].params == {
        "count": 5, "action": "library_to_hand", "max_picks": 1, "optional": True,
        "criteria": {"type": ["artifact", "legendary", "saga"]},
        "rest_destination": "library_bottom_random",
    }


def test_dig_clause_all_matching_to_battlefield_is_mandatory():
    specs = match_clause(
        "reveal the top 6 cards of your library. put all goblin creature cards with mana value 5 or less "
        "from among them onto the battlefield and the rest on the bottom of your library in a random order"
    )
    params = specs[0].params
    assert (params["action"], params["max_picks"], params["optional"]) == ("library_to_battlefield", "all", False)
    assert params["criteria"] == {"all_types": ["goblin", "creature"], "max_mana_value": 5}


def test_dig_clause_else_tail_and_plain_tail():
    specs = match_clause(
        "look at the top 5 cards of your library. you may reveal a creature card from among them and put "
        f"it into your hand. {_BOTTOM}. if you didn't put a card into your hand this way, draw a card"
    )
    assert specs[0].params["else_effects"] == [{"type": "draw", "params": {"count": 1}}]
    specs = match_clause(
        f"look at the top 3 cards of your library. you may reveal a creature card from among them and put it "
        f"into your hand. {_BOTTOM}. you gain 3 life"
    )
    assert [s.type for s in specs] == ["inspect_top_choose", "gain_life"]


def test_dig_clause_shuffled_rest_and_graveyard_rest():
    shuffled = match_clause(
        "reveal the top 4 cards of your library. you may put a land card from among them onto the "
        "battlefield. then shuffle the rest into your library"
    )
    assert shuffled[0].params["rest_destination"] == "library_shuffled"
    graveyard = match_clause(
        "reveal the top 5 cards of your library. you may put a creature or land card from among them "
        "into your hand. put the rest into your graveyard"
    )
    assert graveyard[0].params["rest_destination"] == "graveyard"


@pytest.mark.parametrize("clause", [
    # an announced-X count is a different X under a spell, an ability and a trigger
    "look at the top x cards of your library. you may reveal a creature card from among them and put it "
    f"into your hand. {_BOTTOM}",
    # no statement of where the rest goes
    "look at the top 5 cards of your library. you may reveal a creature card from among them and put it "
    "into your hand",
    # the verb "reveal" without its "and put it" half would silently skip the put
    f"look at the top 5 cards of your library. you may reveal a creature card from among them. {_BOTTOM}",
    # a trailing clause the rest of the table can't claim must fail the whole clause
    "look at the top 5 cards of your library. you may reveal a creature card from among them and put it "
    f"into your hand. {_BOTTOM}. frobnicate the widget",
])
def test_dig_clause_stays_unclaimed_when_any_part_is_unreadable(clause):
    assert match_clause(clause) is None


# ---------------------------------------------------------------------------
# Execute: a real spell on a real engine
# ---------------------------------------------------------------------------

GRISLY = (
    "Reveal the top 5 cards of your library. You may put a creature or land card from among them "
    "into your hand. Put the rest into your graveyard."
)


def test_grisly_salvage_takes_the_picked_card_and_mills_the_rest():
    eng, p1 = _engine()
    _stock(
        p1, _card("Divination", "Sorcery"), _card("Forest", "Basic Land — Forest", cost="", cmc=0),
        _card("Bear"), _card("Shock", "Instant"), _card("Orc Scout", "Creature — Orc"),
        _card("Deep Card", "Sorcery"),
    )
    _cast(eng, p1, GRISLY)
    assert _answer(eng, {"Bear"}) == 1
    assert "Bear" in _names(p1.hand)
    assert sorted(_names(p1.graveyard)) == sorted(["Dig Spell", "Divination", "Forest", "Shock", "Orc Scout"])
    assert _names(p1.library) == ["Deep Card"]  # beyond the top 5: untouched


def test_declining_the_pick_still_moves_the_rest():
    eng, p1 = _engine()
    _stock(p1, _card("Bear"), _card("Shock", "Instant"), _card("A", "Sorcery"), _card("B", "Sorcery"),
           _card("C", "Sorcery"))
    _cast(eng, p1, GRISLY)
    _answer(eng, set())  # decline
    assert "Bear" not in _names(p1.hand)
    assert {"Bear", "Shock"} <= set(_names(p1.graveyard))


def test_the_kind_filter_offers_only_matching_cards():
    eng, p1 = _engine()
    _stock(p1, _card("Orc Scout", "Creature — Orc"), _card("Divination", "Sorcery"),
           _card("Shock", "Instant"), _card("A", "Sorcery"), _card("B", "Sorcery"), _card("C", "Sorcery"))
    _cast(eng, p1, "Look at the top 5 cards of your library. You may reveal an orc card from among them "
                   "and put it into your hand. Put the rest on the bottom of your library in a random order.")
    offered = [o["label"] for o in eng.state.pending_choice["options"] if "instance_id" in o]
    assert offered == ["Orc Scout"]  # the Sorcery in the top 5 is not an "orc"
    _answer(eng, {"Orc Scout"})
    assert _names(p1.hand) == ["Orc Scout"]
    assert len(p1.library) == 5  # four unpicked cards went to the bottom, plus the card below the top 5


def test_all_matching_cards_go_to_the_battlefield_without_asking():
    eng, p1 = _engine()
    _stock(
        p1, _card("Goblin A", "Creature — Goblin", cmc=2), _card("Goblin Big", "Creature — Goblin", cmc=6),
        _card("Elf", "Creature — Elf"), _card("Goblin B", "Creature — Goblin", cmc=3),
        _card("Shock", "Instant"), _card("Goblin Deep", "Creature — Goblin"),
    )
    _cast(eng, p1, "Reveal the top 5 cards of your library. Put all goblin creature cards with mana value "
                   "5 or less from among them onto the battlefield and the rest on the bottom of your "
                   "library in a random order.")
    assert eng.state.pending_choice is None
    assert sorted(o.name for o in eng.state.battlefield if o.name.startswith("Goblin")) == ["Goblin A", "Goblin B"]
    assert {"Goblin Big", "Elf", "Shock"} <= set(_names(p1.library))
    assert "Goblin Deep" in _names(p1.library)  # never revealed


def test_else_tail_runs_when_nothing_was_taken():
    text = ("Look at the top 3 cards of your library. You may reveal a creature card from among them and "
            "put it into your hand. Put the rest on the bottom of your library in a random order. "
            "If you didn't put a card into your hand this way, draw a card.")
    eng, p1 = _engine()
    _stock(p1, _card("A", "Sorcery"), _card("B", "Sorcery"), _card("C", "Sorcery"), _card("Drawn", "Instant"))
    before = len(p1.hand)
    _cast(eng, p1, text)  # no creature in the top 3: nothing to pick
    assert len(p1.hand) == before + 1

    eng, p1 = _engine()
    _stock(p1, _card("Bear"), _card("B", "Sorcery"), _card("C", "Sorcery"), _card("Unrelated", "Instant"))
    before = len(p1.hand)
    _cast(eng, p1, text)
    _answer(eng, {"Bear"})
    assert _names(p1.hand) == ["Bear"] and len(p1.hand) == before + 1  # took one: no extra draw

    eng, p1 = _engine()
    _stock(p1, _card("Bear"), _card("B", "Sorcery"), _card("C", "Sorcery"), _card("Drawn", "Instant"))
    before = len(p1.hand)
    _cast(eng, p1, text)
    _answer(eng, set())  # declined
    assert len(p1.hand) == before + 1  # "if you didn't put a card into your hand": the draw fires


def test_shuffled_rest_stays_in_the_library():
    eng, p1 = _engine()
    _stock(p1, _card("Bear"), _card("A", "Sorcery"), _card("B", "Sorcery"))
    eng.rules.inspect_top_n_choose(
        p1, count=3, action="library_to_hand", criteria={"type": "creature"},
        rest_destination="library_shuffled", optional=True,
    )
    _answer(eng, {"Bear"})
    assert _names(p1.hand) == ["Bear"]
    assert sorted(_names(p1.library)) == ["A", "B"]


def test_dig_clause_battlefield_tapped_and_the_revealed_cards_wording():
    tapped = match_clause(
        "look at the top 6 cards of your library. you may put up to 2 land cards from among them onto the "
        f"battlefield tapped. {_BOTTOM}"
    )
    assert (tapped[0].params["action"], tapped[0].params["max_picks"]) == ("library_to_battlefield_tapped", 2)
    plural = match_clause(
        "look at the top 6 cards of your library. you may reveal any number of artifact cards from among "
        f"them and put the revealed cards into your hand. {_BOTTOM}"
    )
    assert (plural[0].params["action"], plural[0].params["max_picks"]) == ("library_to_hand", "all")


def test_lands_put_onto_the_battlefield_tapped_enter_tapped():
    eng, p1 = _engine()
    _stock(p1, _card("Forest", "Basic Land — Forest", cost="", cmc=0), _card("Bear"),
           _card("Mountain", "Basic Land — Mountain", cost="", cmc=0), _card("Deep", "Sorcery"))
    _cast(eng, p1, "Look at the top 3 cards of your library. You may put up to 2 land cards from among them "
                   "onto the battlefield tapped. Put the rest on the bottom of your library in a random order.")
    _answer(eng, {"Forest", "Mountain"})
    lands = [o for o in eng.state.battlefield if o.name in ("Forest", "Mountain")]
    assert sorted(o.name for o in lands) == ["Forest", "Mountain"]
    assert all(o.tapped for o in lands)
    assert "Bear" in _names(p1.library)

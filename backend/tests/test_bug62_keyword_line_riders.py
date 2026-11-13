"""BUG-62: a keyword line claims the keyword, its cost and reminder text, and nothing else.

`segmenter._KEYWORD_TOKEN_RE` anchors only the keyword word and ends in a greedy ``.*$``, so a rider in the same line
("Disguise {5}{R}. This cost is reduced by ...") or Un-card text that merely opens on a keyword word ("Sneak into your
parents' closet ...") was claimed as a bare keyword while the card counted as MODELED. A further sentence is now claimed
only when the keyword's own parameter carries it (equip/crew "Activate only once each turn", suspend X "X can't be 0").
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.keywords import parse_keywords
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import is_keyword_line


def _unmodeled(card: Card) -> bool:
    result = parse_oracle(card)
    return result.coverage == UNMODELED and not result.modeled


# -- the bug cards ------------------------------------------------------------


def test_disguise_cost_reduction_rider_is_not_falsely_modeled():
    # No turn-face-up cost reduction exists in the engine, so the rider must keep the card UNMODELED (never a full-price disguise).
    card = Card(
        id="fc", name="Fugitive Codebreaker", type_line="Creature — Goblin Rogue", is_creature=True, power=2, toughness=1,
        oracle_text=(
            "Prowess, haste\n"
            "Disguise {5}{R}. This cost is reduced by {1} for each instant and sorcery card in your graveyard.\n"
            "When this creature is turned face up, discard your hand, then draw three cards."
        ),
        keywords=["Prowess", "Haste", "Disguise"],
    )
    result = parse_oracle(card)
    assert not result.modeled
    assert any(line.lower().startswith("disguise") for line in result.unclaimed)


def test_plain_disguise_line_still_parses():
    assert is_keyword_line("disguise {3}{u}")
    assert is_keyword_line("morph {2}{g}")


def test_joke_text_opening_on_a_keyword_word_is_not_claimed():
    card = Card(
        id="fe", name="Fraternal Exaltation", type_line="Sorcery",
        oracle_text="Sneak into your parents' closet to get a deck. Your new brother is joining the game.",
    )
    assert _unmodeled(card)


def test_unpayable_evoke_cost_is_not_a_keyword_line():
    # Cheer: "Evoke—Celebrate an opponent." has no cost the engine can pay.
    assert not is_keyword_line("evoke—celebrate an opponent.")
    card = Card(
        id="ch", name="Cheer", type_line="Creature — Elemental", is_creature=True, power=2, toughness=2,
        oracle_text="Lifelink, haste\nEvoke—Celebrate an opponent.",
        keywords=["Lifelink", "Haste", "Evoke"],
    )
    assert _unmodeled(card)


def test_real_evoke_costs_still_parse():
    assert is_keyword_line("evoke {2}{r}")
    assert is_keyword_line("evoke—exile a red card from your hand.")


def test_casualty_copy_rider_is_not_swallowed():
    assert not is_keyword_line("casualty x. the copy isn't legendary and has starting loyalty x.")
    assert is_keyword_line("casualty 2")


# -- real keyword lines keep parsing -----------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "flying",
        "flying, first strike",
        "ward {2}",
        "ward—pay 3 life.",
        "equip {1}",
        "equip {0}. activate only once each turn.",
        "crew 1",
        "crew 1. activate only once each turn.",
        "kicker {1}{r}",
        "cycling {2}",
        "flashback {3}{r}",
        "flashback—{1}{b}, pay 3 life.",
        "suspend 4—{r}",
        "suspend x—{x}{g}{g}. x can't be 0.",
        "craft with artifact {2}{r}",
        "disguise {3}{u}",
        "protection from blue and from red",
        "partner with some name",
    ],
)
def test_real_keyword_lines_still_claim(line):
    assert is_keyword_line(line)


@pytest.mark.parametrize(
    "line",
    [
        "flying. draw a card.",
        "kicker {1}{r}. this costs {1} less.",
        "equip {3}. this ability costs {1} less to activate.",
        "crew 2. activate only during your turn.",
        "flashback {3}{r}. flashback costs you pay cost {1} less.",
    ],
)
def test_a_second_sentence_is_never_swallowed(line):
    assert not is_keyword_line(line)


# -- carried riders: the spec and the engine honour them ----------------------


def _vehicle(oracle: str) -> Card:
    return Card(
        id="v", name="Test Locomotive", type_line="Artifact — Vehicle", oracle_text=oracle,
        keywords=["Crew"], vehicle_power=3, vehicle_toughness=3,
    )


def _bear(name: str) -> Card:
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True, power=2, toughness=2)


def _put(state, card: Card) -> GameObject:
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def test_crew_once_each_turn_is_carried_into_the_spec():
    card = _vehicle("Crew 1. Activate only once each turn. (Tap any number of creatures you control with total power 1 or more: This Vehicle becomes an artifact creature until end of turn.)")
    assert parse_oracle(card).modeled
    crew = [s.keyword for s in parse_keywords(card) if s.keyword["name"] == "crew"][0]
    assert crew["n"] == 1 and crew["once_per_turn"] is True
    plain = [s.keyword for s in parse_keywords(_vehicle("Crew 1")) if s.keyword["name"] == "crew"][0]
    assert "once_per_turn" not in plain


def test_crew_once_each_turn_executes_in_the_engine():
    eng = GameEngine.new_game([("p1", "p1", []), ("p2", "p2", [])], starting_life=20, starting_hand=0)
    p1 = eng.state.player_by_id("p1")
    veh = _put(eng.state, _vehicle("Crew 1. Activate only once each turn."))
    a, b = _put(eng.state, _bear("A")), _put(eng.state, _bear("B"))
    ability = veh.activated_abilities[0]
    assert ability.once_per_turn is True
    eng.activate_ability(p1, veh, 0, x=0, tap_choices=[a.instance_id])
    eng.resolve_until_stable()
    assert a.tapped is True
    assert eng.can_activate(p1, veh, ability, x=0, tap_choices=[b.instance_id]) is False

    # Without the rider the same vehicle crews again.
    eng2 = GameEngine.new_game([("p1", "p1", []), ("p2", "p2", [])], starting_life=20, starting_hand=0)
    p1b = eng2.state.player_by_id("p1")
    veh2 = _put(eng2.state, _vehicle("Crew 1"))
    a2, b2 = _put(eng2.state, _bear("A")), _put(eng2.state, _bear("B"))
    eng2.activate_ability(p1b, veh2, 0, x=0, tap_choices=[a2.instance_id])
    eng2.resolve_until_stable()
    assert eng2.can_activate(p1b, veh2, veh2.activated_abilities[0], x=0, tap_choices=[b2.instance_id]) is True


def test_equip_once_each_turn_still_carried():
    card = Card(
        id="la", name="Leather Armor", type_line="Artifact — Equipment",
        oracle_text="Equipped creature gets +1/+1.\nEquip {0}. Activate only once each turn.",
        keywords=["Equip"],
    )
    equip = [s.keyword for s in parse_keywords(card) if s.keyword["name"] == "equip"][0]
    assert equip["once_per_turn"] is True


def test_suspend_x_nonzero_rider_is_carried():
    card = Card(
        id="de", name="Test Suspender", type_line="Creature — Beast", is_creature=True, power=1, toughness=1,
        oracle_text="Suspend X—{X}{G}{G}. X can't be 0.", keywords=["Suspend"],
    )
    suspend = [s.keyword for s in parse_keywords(card) if s.keyword["name"] == "suspend"][0]
    assert suspend["min_x"] == 1


# -- exert decision: the keyword line reaches the engine ----------------------


def test_bare_exert_line_is_claimed_and_the_engine_exerts():
    # Decision: "You may exert ~ as it attacks." stays a keyword-line claim. The engine models exert off the Scryfall `Exert`
    # keyword (`combat.has`, `declare_attackers(exert=True)`), so the claim drops nothing.
    card = Card(
        id="bs", name="Plain Exerter", type_line="Creature — Human", is_creature=True, power=2, toughness=2,
        oracle_text="You may exert ~ as it attacks. (It won't untap during your next untap step.)", keywords=["Exert"],
    )
    assert parse_oracle(card).modeled
    eng = GameEngine.new_game([("p1", "p1", []), ("p2", "p2", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    attacker = _put(eng.state, card)
    eng.declare_attackers(eng.state.active_player, [{"attacker": attacker, "exert": True}])
    assert attacker.exerted_this_turn is True and attacker.skip_next_untap is True

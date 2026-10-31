"""PAR-208 slice 2: "search target opponent's/player's library for <criteria> and exile it / put it onto the battlefield
under your control. Then that player shuffles." (RULE 701.19a, RULE 110.2), executed in the real engine."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.game import creature, make_engine

_DB = CardDatabase(DB_PATH)


def _named(name: str) -> Card:
    card = _DB.get_card(name)
    assert card is not None, name
    return card


def _cast(spell: str, mana: dict[str, int], library: list[Card], target: str = "p2"):
    eng = make_engine([creature(f"Mine {i}") for i in range(3)], library, hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    obj = GameObject(_named(spell), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    p1.mana_pool.add_many(mana)
    eng.begin_turn()
    state.current_step = "main1"
    eng.cast_spell(p1, obj, targets=[state.player_by_id(target)])
    eng.resolve_until_stable()
    return eng, state


def _answer_search(eng, name: str) -> None:
    choice = eng.state.pending_choice
    assert choice is not None and choice.get("kind") == "search"
    assert choice.get("player_id") == "p1"  # the caster answers (RULE 701.19a)
    pick = next(o for o in choice["eligible"] if o["name"] == name)
    eng.rules.resolve_choice(pick["instance_id"])


def test_bribery_puts_the_opponents_creature_onto_the_battlefield_under_your_control():
    eng, state = _cast("Bribery", {"U": 3, "C": 2}, [creature("Big Guy", power=5, toughness=5), creature("Small")])
    p2 = state.player_by_id("p2")
    _answer_search(eng, "Big Guy")
    eng.resolve_until_stable()
    big = next(o for o in state.battlefield if o.name == "Big Guy")
    assert big.controller_id == "p1" and big.owner_id == "p2"
    assert big not in p2.library


def test_bitter_ordeal_exiles_from_the_targeted_players_library_and_shuffles_it():
    eng, state = _cast("Bitter Ordeal", {"B": 1, "C": 2}, [creature(f"Lib {i}") for i in range(4)])
    p2 = state.player_by_id("p2")
    before = len(p2.library)
    _answer_search(eng, "Lib 2")
    eng.resolve_until_stable()
    assert len(p2.library) == before - 1
    assert [o.name for o in p2.exile] == ["Lib 2"]


def test_extract_may_target_the_caster_but_bribery_may_not():
    extract = parse_oracle(_named("Extract")).effect_specs[0].effects[0].params
    bribery = parse_oracle(_named("Bribery")).effect_specs[0].effects[0].params
    assert extract.get("target_any_player") is True
    assert not bribery.get("target_any_player")


def test_denying_wind_searches_for_up_to_seven_and_exiles_them():
    eng, state = _cast("Denying Wind", {"U": 2, "C": 7}, [creature(f"Lib {i}") for i in range(9)])
    p2 = state.player_by_id("p2")
    for i in range(7):
        _answer_search(eng, f"Lib {i}")
        eng.resolve_until_stable()
        if state.pending_choice is None:
            break
    assert len(p2.exile) == 7


@pytest.mark.parametrize("name", [
    "Acquire", "Bitter Ordeal", "Bribery", "Denying Wind", "Eternal Dominion", "Extract", "Inevitable Betrayal",
    "Jester's Cap", "Sadistic Sacrament", "Supreme Inquisitor",
])
def test_claimed_cards_are_modeled(name):
    assert parse_oracle(_named(name)).coverage == MODELED


@pytest.mark.parametrize("clause", [
    "search target opponent's library for a card and exile it",  # no trailing shuffle: not this construct
    "search that player's library for a card and exile it. then that player shuffles",  # referent, PAR-210 scope
    "search target player's library for x cards and exile them. then that player shuffles",  # dynamic X amount
])
def test_near_misses_stay_unclaimed(clause):
    assert match_clause(clause) is None


def test_sadistic_sacrament_unkicked_exiles_at_most_three():
    eng, state = _cast("Sadistic Sacrament", {"B": 3}, [creature(f"Lib {i}") for i in range(8)])
    p2 = state.player_by_id("p2")
    for i in range(5):
        if state.pending_choice is None:
            break
        _answer_search(eng, f"Lib {i}")
        eng.resolve_until_stable()
    assert len(p2.exile) == 3 and len(p2.library) == 5

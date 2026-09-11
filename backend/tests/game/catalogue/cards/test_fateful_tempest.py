"""Fateful Tempest resolves its vote outcome."""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _tempest_card():
    return Card(id="ft", name="Fateful Tempest", type_line="Sorcery", is_sorcery=True,
                oracle_text=(
                    "Council's dilemma — Starting with you, each player votes for past "
                    "or present. You mill a card for each past vote, then Fateful "
                    "Tempest deals damage to each opponent equal to the total mana "
                    "value of cards milled this way. Exile the top card of your library "
                    "for each present vote. Until the end of your next turn, you may "
                    "play the exiled cards."))


def test_registered_and_binds():
    assert is_registered("Fateful Tempest")
    spec = _REGISTRY["fateful tempest"]()[0]
    spec.validate()
    assert spec.effects[0].type == "vote"
    pv = spec.effects[0].params["per_vote_specs"]
    assert pv[0]["effects"][0]["type"] == "seq"
    assert pv[1]["effects"][0]["type"] == "impulsive_draw"
    src = GameObject(_tempest_card(), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    bind_ability(spec, src)


def test_specs_for_real_card():
    assert specs_for(_tempest_card())


def _stock_library(player, n, mv=2):
    for i in range(n):
        c = Card(id=f"c{i}", name=f"Card{i}", type_line="Sorcery", is_sorcery=True,
                 mana_cost_string="{1}{R}", converted_mana_cost=mv)
        player.add_to_zone(GameObject(c, owner_id=player.id, zone=Zone.LIBRARY), Zone.LIBRARY)


def test_all_past_votes_mill_and_damage_each_opponent_by_total_mv():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    _stock_library(p1, 5)  # each card MV 2

    src = GameObject(_tempest_card(), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    bind_from_catalogue(src)

    spec = _REGISTRY["fateful tempest"]()[0]
    eng.rules._request_vote(
        source=src, controller_id="p1", options=["past", "present"],
        per_vote_specs=spec.effects[0].params["per_vote_specs"],
    )
    eng.resolve_pending_choice("0")  # p1 -> past
    eng.resolve_pending_choice("0")  # p2 -> past  => 2 past votes
    eng.resolve_until_stable()

    # milled 2 cards (MV 2 each) -> 4 damage to each opponent
    assert len(p1.graveyard) == 2
    assert p2.life == 16
    assert p1.life == 20  # "each opponent", not you


def test_present_votes_exile_impulse_playable():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    _stock_library(p1, 5)

    src = GameObject(_tempest_card(), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    bind_from_catalogue(src)
    spec = _REGISTRY["fateful tempest"]()[0]
    eng.rules._request_vote(
        source=src, controller_id="p1", options=["past", "present"],
        per_vote_specs=spec.effects[0].params["per_vote_specs"],
    )
    eng.resolve_pending_choice("1")  # p1 -> present
    eng.resolve_pending_choice("1")  # p2 -> present  => 2 present votes
    eng.resolve_until_stable()

    exiled = [o for o in p1.exile]
    assert len(exiled) == 2
    for o in exiled:
        assert o.instance_id in eng.state.temp_play_permissions

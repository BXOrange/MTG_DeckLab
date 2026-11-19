"""PAR-288 (P1-F "up to N"): graveyard picks that may name no card at all (RULE 115.1a / 601.2c).

Swiftgear Drake and Conjurer's Bauble put up to one target card on the bottom of a library; Bilbo returns up to one
nonland permanent card with mana value 3 or less. The player may pick fewer than the maximum (zero included), the
rest of the ability must still happen, and a card outside the filter must never be offered."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.deck_batch import activate, answer, attack, card, filler, game, put_on_battlefield

NEWLY = ["Swiftgear Drake", "Conjurer's Bauble", "Bilbo, Unexpected Adventurer"]


@pytest.mark.parametrize("name", NEWLY)
def test_cards_are_modeled(name):
    assert parse_oracle(CardDatabase(DB_PATH).get_card(name)).coverage == MODELED


def test_parse_shapes():
    (spec,) = match_clause("put up to one target card from a graveyard on the bottom of its owner's library")
    assert spec.params == {"target_kind": "any_graveyard_card", "position": "bottom", "optional": True}
    (plain,) = match_clause("put target card from a graveyard on the bottom of its owner's library")
    assert "optional" not in plain.params                         # the printed "target" is mandatory
    (bilbo,) = match_clause("put up to 1 target nonland permanent card with mana value 3 or less from a graveyard "
                            "onto the battlefield under its owner's control")
    assert bilbo.params["max_mana_value"] == 3 and bilbo.params["optional"] is True


def _grave(engine, obj, player):
    p = engine.state.player_by_id(player)
    engine.state.battlefield[:] = [o for o in engine.state.battlefield if o is not obj]
    obj.zone = Zone.GRAVEYARD
    p.graveyard.append(obj)
    return obj


def test_swiftgear_drake_puts_a_chosen_card_from_either_graveyard_on_the_bottom_of_its_owners_library():
    engine = game()
    mine = _grave(engine, filler(engine, "Mine", power=1, toughness=1), "p1")
    theirs = _grave(engine, filler(engine, "Theirs", power=1, toughness=1, player="p2"), "p2")
    put_on_battlefield(engine, "Swiftgear Drake")
    choice = engine.state.pending_choice
    ids = {str(o["id"]) for o in choice["options"]}
    assert {str(mine.instance_id), str(theirs.instance_id)} <= ids
    answer(engine, pick=lambda c: str(theirs.instance_id))
    engine.resolve_until_stable()
    assert theirs.zone == Zone.LIBRARY and engine.state.player_by_id("p2").library[0] is theirs   # index 0 is the bottom
    assert mine.zone == Zone.GRAVEYARD                             # the bystander in the other graveyard stays


def test_swiftgear_drake_may_pick_no_card():
    engine = game()
    mine = _grave(engine, filler(engine, "Mine", power=1, toughness=1), "p1")
    put_on_battlefield(engine, "Swiftgear Drake")
    answer(engine, pick=lambda c: "decline")
    engine.resolve_until_stable()
    assert mine.zone == Zone.GRAVEYARD


def test_swiftgear_drake_with_both_graveyards_empty_does_nothing():
    engine = game()
    put_on_battlefield(engine, "Swiftgear Drake")
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None


def test_conjurers_bauble_draws_even_when_it_names_no_card():
    engine = game()
    bauble = card(engine, "Conjurer's Bauble")
    before = len(engine.state.player_by_id("p1").hand)
    activate(engine, bauble)
    answer(engine, pick=lambda c: "decline")
    engine.resolve_until_stable()
    assert len(engine.state.player_by_id("p1").hand) == before + 1  # the draw is not tied to the optional pick
    assert bauble.zone == Zone.GRAVEYARD                            # sacrificed as a cost


def test_conjurers_bauble_puts_the_chosen_card_on_the_bottom_and_never_offers_an_opponents_card():
    engine = game()
    bauble = card(engine, "Conjurer's Bauble")
    mine = _grave(engine, filler(engine, "Mine", power=1, toughness=1), "p1")
    theirs = _grave(engine, filler(engine, "Theirs", power=1, toughness=1, player="p2"), "p2")
    from mtg_analyzer.game.targeting import legal_targets
    ability = bauble.activated_abilities[0]
    offered = {o["instance_id"] for o in legal_targets(
        engine.state, "p1", next(e for e in ability.effects if getattr(e, "target_spec", None) is not None).target_spec)}
    assert offered == {mine.instance_id}
    activate(engine, bauble, targets=[mine])
    assert mine.zone == Zone.LIBRARY and engine.state.player_by_id("p1").library[0] is mine
    assert theirs.zone == Zone.GRAVEYARD


def _bilbo_hits(engine, bilbo):
    engine.rules.deal_combat_damage([(engine.state.player_by_id("p2"), 1, bilbo)])
    engine.resolve_until_stable()


def test_bilbo_returns_up_to_one_cheap_nonland_permanent_card_under_its_owners_control():
    engine = game()
    bilbo = card(engine, "Bilbo, Unexpected Adventurer")
    cheap = _grave(engine, filler(engine, "Cheap", mv=3, power=1, toughness=1, player="p2"), "p2")
    dear = _grave(engine, filler(engine, "Dear", mv=4, power=1, toughness=1, player="p2"), "p2")
    spell = _grave(engine, filler(engine, "Spell", type_line="Instant", mv=1, player="p2"), "p2")
    land = _grave(engine, filler(engine, "Land", type_line="Land", player="p2"), "p2")
    _bilbo_hits(engine, bilbo)
    choice = engine.state.pending_choice
    offered = {str(o["id"]) for o in choice["options"]}
    assert "decline" in offered                                      # "up to one": zero is legal
    assert offered - {"decline"} == {str(cheap.instance_id)}                       # mana value 4, an instant and a land are not offered
    answer(engine, pick=lambda c: str(cheap.instance_id))
    engine.resolve_until_stable()
    assert cheap.zone == Zone.BATTLEFIELD and cheap.controller_id == "p2"   # its owner's, not Bilbo's controller
    assert {dear.zone, spell.zone, land.zone} == {Zone.GRAVEYARD}


def test_bilbo_may_decline_and_every_card_stays_put():
    engine = game()
    bilbo = card(engine, "Bilbo, Unexpected Adventurer")
    cheap = _grave(engine, filler(engine, "Cheap", mv=3, power=1, toughness=1, player="p2"), "p2")
    _bilbo_hits(engine, bilbo)
    answer(engine, pick=lambda c: "decline")
    engine.resolve_until_stable()
    assert cheap.zone == Zone.GRAVEYARD

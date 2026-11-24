"""PAR-286 milestone 4: the cost "Put a card an opponent owns from exile into that player's graveyard".

RULE 118.3 / 602.2b: the cost is paid only with a real card in an opponent's exile zone, which moves to its owner's
graveyard (RULE 400.3). Cryptic Cruiser, Oracle of Dust and Void Attendant are activated on the real engine: payable
when an opponent's exiled card exists, refused otherwise (a card in the opponent's graveyard or the activator's own
exile is a near miss), actually paid, and the effect resolves.
"""

from __future__ import annotations

import copy

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.costs import parse_activation_cost
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.catalogue.cost_text import scan_cost_text
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.game_session import GameSession
from tests.support.deck_batch import RICH, activate, card, filler, game, main_phase

COST = "{2}{u}, put a card an opponent owns from exile into that player's graveyard"
CARDS = ["Cryptic Cruiser", "Oracle of Dust", "Void Attendant"]


@pytest.mark.parametrize("name", CARDS)
def test_cards_are_modeled(name):
    card_ = CardDatabase(DB_PATH).get_card(name)
    assert card_ is not None
    assert parse_oracle(card_).coverage == MODELED


def test_cost_grammar_reads_the_whole_cost_and_nothing_nearby():
    assert scan_cost_text(COST).leftover is None
    assert parse_activation_cost(COST).put_opponent_exile_to_graveyard is True
    # near misses: your own exile, or a card you own, is not the printed cost
    assert scan_cost_text("{2}, put a card you own from exile into your graveyard").leftover is not None
    assert not parse_activation_cost("{2}").put_opponent_exile_to_graveyard


def _exiled(engine, owner, name="Exiled"):
    obj = filler(engine, name, type_line="Creature", player=owner, zone=Zone.EXILE)
    return obj


def _can(engine, source):
    p = engine.state.player_by_id("p1")
    main_phase(engine)
    p.mana_pool.add_many(RICH)
    return engine.can_activate(p, source, source.activated_abilities[0])


def _setup(name="Cryptic Cruiser"):
    engine = game()
    source = card(engine, name)
    return engine, source


def test_cryptic_cruiser_pays_by_moving_the_opponents_exiled_card_and_taps_the_target():
    engine, cruiser = _setup()
    victim = filler(engine, "Victim", type_line="Creature", player="p2", power=2, toughness=2)
    exiled = _exiled(engine, "p2")
    p2 = engine.state.player_by_id("p2")
    assert exiled in p2.exile
    engine.state.player_by_id("p1").mana_pool.add_many(RICH)
    activate(engine, cruiser, targets=[victim])
    assert exiled.zone == Zone.GRAVEYARD and exiled in p2.graveyard and exiled not in p2.exile
    assert victim.tapped is True


def test_cost_is_refused_without_an_opponents_exiled_card():
    engine, cruiser = _setup()
    victim = filler(engine, "Victim", type_line="Creature", player="p2", power=2, toughness=2)
    own_exiled = _exiled(engine, "p1", "OwnExiled")          # near miss: my own exile
    gy = filler(engine, "InGraveyard", type_line="Creature", player="p2", zone=Zone.GRAVEYARD)  # near miss: not exile
    assert not _can(engine, cruiser)
    with pytest.raises(Exception):
        activate(engine, cruiser, targets=[victim])
    assert victim.tapped is False
    assert own_exiled.zone == Zone.EXILE and gy.zone == Zone.GRAVEYARD
    _exiled(engine, "p2")
    assert _can(engine, cruiser)


def test_oracle_of_dust_draws_then_discards():
    engine, oracle = _setup("Oracle of Dust")
    p1 = engine.state.player_by_id("p1")
    filler(engine, "Hand", type_line="Creature", zone=Zone.HAND)
    exiled = _exiled(engine, "p2")
    p1.mana_pool.add_many(RICH)
    before_library = len(p1.library)
    activate(engine, oracle)
    assert exiled.zone == Zone.GRAVEYARD
    assert len(p1.library) == before_library - 1


def test_void_attendant_makes_a_scion_with_a_sacrifice_mana_ability():
    engine, attendant = _setup("Void Attendant")
    exiled = _exiled(engine, "p2")
    engine.state.player_by_id("p1").mana_pool.add_many(RICH)
    activate(engine, attendant)
    assert exiled in engine.state.player_by_id("p2").graveyard
    scions = [o for o in engine.state.battlefield if o.controller_id == "p1" and "Scion" in o.card.type_line]
    assert len(scions) == 1


def test_payment_survives_clone():
    engine, cruiser = _setup()
    _exiled(engine, "p2")
    clone = copy.deepcopy(engine.state)
    assert any(c.zone == Zone.EXILE for c in clone.player_by_id("p2").exile)
    assert len(clone.player_by_id("p2").exile) == len(engine.state.player_by_id("p2").exile) == 1


def _two_exiled():
    engine, cruiser = _setup()
    victim = filler(engine, "Victim", type_line="Creature", player="p2", power=2, toughness=2)
    first = _exiled(engine, "p2", "First")
    second = _exiled(engine, "p2", "Second")
    engine.state.player_by_id("p1").mana_pool.add_many(RICH)
    return engine, cruiser, victim, first, second


def test_the_activators_pick_decides_which_opponent_card_is_put_into_the_graveyard():
    engine, cruiser, victim, first, second = _two_exiled()
    activate(engine, cruiser, targets=[victim], hand_card_choices=[second.instance_id])
    assert second.zone == Zone.GRAVEYARD and first.zone == Zone.EXILE
    assert victim.tapped is True


def test_a_pick_outside_the_opponent_exile_pool_is_refused():
    engine, cruiser, victim, first, second = _two_exiled()
    own = _exiled(engine, "p1", "OwnExiled")
    for bad in ([own.instance_id], [first.instance_id, second.instance_id], [victim.instance_id]):
        with pytest.raises(ValueError, match="cannot activate"):
            activate(engine, cruiser, targets=[victim], hand_card_choices=bad)
    assert first.zone == second.zone == own.zone == Zone.EXILE
    assert victim.tapped is False


def test_without_a_pick_the_first_eligible_card_pays():
    engine, cruiser, victim, first, second = _two_exiled()
    activate(engine, cruiser, targets=[victim])
    assert first.zone == Zone.GRAVEYARD and second.zone == Zone.EXILE


def test_offer_lists_the_pool_and_the_session_wire_applies_the_pick():
    engine, cruiser, victim, first, second = _two_exiled()
    _exiled(engine, "p1", "OwnExiled")
    p1 = engine.state.player_by_id("p1")
    action = next(a for a in engine.legal_actions(p1)
                  if a.get("type") == "activate_ability" and a.get("instance_id") == cruiser.instance_id)
    cost = action["opponent_exile_cost"]
    assert cost["count"] == 1
    assert {o["instance_id"] for o in cost["options"]} == {first.instance_id, second.instance_id}
    GameSession(engine, mode="replay", require_setup=False).apply_action({
        "type": "activate_ability", "instance_id": cruiser.instance_id, "ability_index": 0,
        "targets": [{"instance_id": victim.instance_id}], "opponent_exile_choices": [second.instance_id],
    })
    engine.resolve_until_stable()
    assert second.zone == Zone.GRAVEYARD and first.zone == Zone.EXILE

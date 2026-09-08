"""Abstract Performance separates revealed cards into piles and grants a cast window."""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _ap_card():
    return Card(id="ap", name="Abstract Performance", type_line="Sorcery", is_sorcery=True,
                oracle_text=("Exile the top four cards of your library in a face-down "
                             "pile, then exile the top four cards of your library in a "
                             "face-up pile. An opponent chooses one of those piles. Put "
                             "that pile into your graveyard. Look at the cards in the "
                             "other pile. You may cast a spell from among them without "
                             "paying its mana cost. Put the rest into your hand."))


def test_registered_and_binds():
    assert is_registered("Abstract Performance")
    spec = _REGISTRY["abstract performance"]()[0]
    spec.validate()
    assert spec.effects[0].type == "abstract_performance"
    src = GameObject(_ap_card(), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    bind_ability(spec, src)


def test_specs_for_real_card():
    assert specs_for(_ap_card())


def test_splits_piles_grants_one_free_cast_rest_to_hand():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    p1 = eng.state.player_by_id("p1")
    # first pile (top 4): all MV 1 -> total 4 ; second pile (next 4): all MV 3 -> total 12
    # -> second pile (higher MV) goes to graveyard, first pile kept
    for mv, tag in [(3, "B"), (3, "B"), (3, "B"), (3, "B"),
                    (1, "A"), (1, "A"), (1, "A"), (1, "A")]:
        p1.add_to_zone(GameObject(Card(id=f"{tag}{mv}{id(object())}", name=f"{tag}card",
                                       type_line="Sorcery", is_sorcery=True,
                                       converted_mana_cost=mv),
                                  owner_id="p1", zone=Zone.LIBRARY), Zone.LIBRARY)
    src = GameObject(_ap_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    eng.state.add_to_battlefield(src)

    eng.rules._apply_effect_specs([{"type": "abstract_performance", "params": {}}], src)
    eng.resolve_until_stable()

    assert {o.card.name for o in p1.graveyard} == {"Bcard"}   # higher-MV pile
    kept = [o for o in p1.hand] + [o for o in p1.exile]
    assert len(kept) == 4
    assert all(o.card.name == "Acard" for o in kept)
    assert len(p1.exile) == 1  # one free-cast granted
    free = p1.exile[0]
    assert free.instance_id in eng.state.free_cast_instance_ids
    assert len(p1.hand) == 3

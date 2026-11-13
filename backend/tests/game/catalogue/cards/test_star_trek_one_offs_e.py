"""Star Trek (TRK/TRC) one-off cards, batch E: real cached cards on a real engine."""

from __future__ import annotations

from mtg_analyzer.game import combat
from tests.support.star_trek import cast, game, on_battlefield, stock_library, vanilla


def _answer(engine, option_id):
    """Resolve the open choice with ``option_id`` (the test fails if it is not offered)."""
    choice = engine.state.pending_choice
    assert choice is not None and any(o["id"] == option_id for o in choice["options"]), choice
    engine.resolve_pending_choice(option_id)


def _keep_surveilled_on_top(engine):
    """RULE 701.31: surveil 2, leave both on top, keeping the offered order."""
    while engine.state.pending_choice and engine.state.pending_choice["kind"] == "surveil":
        choice = engine.state.pending_choice
        keep = "decline" if any(o["id"] == "decline" for o in choice["options"]) else choice["options"][0]["id"]
        engine.resolve_pending_choice(keep)


def _belanna_activate(top_type_line):
    """B'Elanna activated with ``top_type_line`` on top of a stocked library; surveil kept on top."""
    engine, p1, p2 = game()
    belanna = on_battlefield(engine, "p1", "B'Elanna Torres, Scrapper")
    stock_library(engine, "p1", 3)
    top = stock_library(engine, "p1", 1, type_line=top_type_line)[0]  # the card revealed after surveil
    p1.mana_pool.add_many({"C": 2})
    engine.activate_ability(p1, belanna)
    engine.resolve_until_stable()
    _keep_surveilled_on_top(engine)
    return engine, p1, belanna, top


def test_belanna_has_vigilance_and_trample():
    engine, p1, p2 = game()
    belanna = on_battlefield(engine, "p1", "B'Elanna Torres, Scrapper")
    assert combat.has(belanna, "vigilance") and combat.has(belanna, "trample")


def test_belanna_draws_on_a_revealed_artifact_and_gets_no_counters():
    engine, p1, belanna, top = _belanna_activate("Artifact")
    _answer(engine, "reveal")
    engine.resolve_until_stable()
    assert top in p1.hand and belanna.counters.get("+1/+1", 0) == 0
    assert belanna.tapped


def test_belanna_gets_two_counters_when_the_revealed_card_is_not_an_artifact():
    engine, p1, belanna, top = _belanna_activate("Land")
    _answer(engine, "reveal")
    engine.resolve_until_stable()
    assert top not in p1.hand and top in p1.library
    assert belanna.counters.get("+1/+1") == 2


def test_belanna_gets_two_counters_when_the_reveal_is_declined_even_over_an_artifact():
    engine, p1, belanna, top = _belanna_activate("Artifact")
    hand = len(p1.hand)
    _answer(engine, "keep_hidden")
    engine.resolve_until_stable()
    assert len(p1.hand) == hand and belanna.counters.get("+1/+1") == 2


def _land(engine, player_id, name):
    """A plain land permanent with the given name (the differently-named count keys on the name)."""
    from mtg_analyzer.models.cards.card import Card
    from mtg_analyzer.models.game.game_object import GameObject, Zone

    obj = GameObject(Card(id=name, name=name, type_line="Basic Land — Forest" if name == "Forest" else "Land",
                          is_land=True), owner_id=player_id, zone=Zone.BATTLEFIELD)
    obj.controller_id = player_id
    engine.state.add_to_battlefield(obj)
    return obj


def test_euroakus_makes_one_token_per_differently_named_land():
    engine, p1, p2 = game("Euroakus")
    for name in ("Forest", "Forest", "Island", "Wastes"):
        _land(engine, "p1", name)
    cast(engine, p1, p1.hand[0])
    tokens = [o for o in engine.state.battlefield if o.is_token and o.controller_id == "p1"]
    assert len(tokens) == 3  # RULE 201.2: Forest, Island, Wastes
    assert all(t.power == 1 and t.toughness == 1 for t in tokens)
    assert all("Wizard" in t.card.type_line and "Human" in t.card.type_line for t in tokens)


def test_euroakus_draws_per_wizard_then_pumps_wizards_by_hand_size():
    engine, p1, p2 = game()
    euroakus = on_battlefield(engine, "p1", "Euroakus")
    wizard = vanilla(engine, "p1", "Apprentice", 1, 1)
    wizard.card.type_line = "Creature — Human Wizard"
    bear = vanilla(engine, "p1", "Bear")
    stock_library(engine, "p1", 5)
    p1.mana_pool.add_many({"G": 1, "U": 1, "C": 4})
    engine.activate_ability(p1, euroakus)
    engine.resolve_until_stable()
    assert len(p1.hand) == 2  # Euroakus is a Wizard too: one draw per Wizard
    assert wizard.power == 1 + 2  # +1/+1 for each of the two cards in hand
    assert euroakus.power == euroakus.card.power + 2
    assert bear.power == 2  # not a Wizard


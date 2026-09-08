"""cEDH staples cube — batch 20: the "tapped for mana" event primitive
(RULE 605.1 — `EventType.TAPPED_FOR_MANA`).

New core capability: `GameEngine.tap_for_mana` fires `TAPPED_FOR_MANA` after
the mana lands in the pool — carrying the tapped permanent's ``instance_id``,
its ``object_types`` (so "taps a land"/"taps a nonland permanent" filters via
the ordinary ``"group"`` subject machinery), the ``controller_id`` that tapped
it, and the ``produced`` mana — off a *genuine mana-ability tap only*, never a
plain tap-cost or an attack.

Fully unblocks **Price of Glory** ("whenever a player taps a land for mana, if
it's not that player's turn, destroy that land"), which composes this event
with the ``not_controllers_turn`` intervening-if (batch-20 addition) and the
reflexive "destroy that land" target (batch 16). Kinnan (needs "add one mana of
any type that permanent produced" — a dynamic produced-mana amount), Wild
Growth (a *triggered mana ability*, RULE 605.1b/605.4 — must resolve
immediately into the pool, not via the stack) and Mana Web (tap *all* matching
lands) all consume this same event but carry a second gap and stay deferred.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import ability_catalogue as ac
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _engine() -> GameEngine:
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=40, starting_hand=0
    )
    eng.begin_turn()  # p1 is the active player
    eng.state.current_step = "main1"
    return eng


def _forest(owner: str) -> GameObject:
    """A basic land with a plain "{T}: Add {G}." mana ability, on the battlefield."""
    card = Card(
        id=f"forest-{owner}", name="Forest",
        type_line="Basic Land — Forest",
        oracle_text="({T}: Add {G}.)",
    )
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    return obj


def _mana_dork(owner: str) -> GameObject:
    """A nonland creature with a "{T}: Add {G}." mana ability (a control that a
    land-only "tapped for mana" trigger must NOT fire for)."""
    card = Card(
        id=f"dork-{owner}", name="Llanowar Elves",
        type_line="Creature — Elf Druid", is_creature=True, power=1, toughness=1,
        oracle_text="{T}: Add {G}.",
    )
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    return obj


def _price_of_glory(eng, controller: str = "p1") -> GameObject:
    card = CardDatabase(DEFAULT_DB_PATH).get_card("Price of Glory") if DEFAULT_DB_PATH.exists() else None
    if card is None:
        card = Card(
            id="pog", name="Price of Glory", type_line="Enchantment",
            oracle_text="Whenever a player taps a land for mana, if it's not "
                        "that player's turn, destroy that land.",
        )
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


# ---------------------------------------------------------------------------
# 0. Registration + playability
# ---------------------------------------------------------------------------


def test_price_of_glory_registered_and_playable():
    assert "price of glory" in ac._REGISTRY
    if DEFAULT_DB_PATH.exists():
        card = CardDatabase(DEFAULT_DB_PATH).get_card("Price of Glory")
        if card is not None:
            assert ac.specs_for(card), "Price of Glory produced no specs"


# ---------------------------------------------------------------------------
# 1. The TAPPED_FOR_MANA event itself
# ---------------------------------------------------------------------------


def test_tap_for_mana_fires_tapped_for_mana_with_payload():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    forest = _forest("p1")
    eng.state.add_to_battlefield(forest)

    seen: list[GameEvent] = []
    eng.state.subscribe(lambda ev: seen.append(ev) if ev.type == EventType.TAPPED_FOR_MANA else None)

    eng.tap_for_mana(p1, forest)

    assert len(seen) == 1
    ev = seen[0]
    assert ev.get("instance_id") == forest.instance_id
    assert ev.get("controller_id") == "p1"
    assert "land" in ev.get("object_types")
    assert ev.get("produced") == {"G": 1}


# ---------------------------------------------------------------------------
# 2. Price of Glory behaviour
# ---------------------------------------------------------------------------


def test_price_of_glory_destroys_a_land_tapped_on_another_players_turn():
    eng = _engine()  # p1's turn
    _price_of_glory(eng, controller="p1")
    p2 = eng.state.player_by_id("p2")
    forest = _forest("p2")
    eng.state.add_to_battlefield(forest)

    eng.tap_for_mana(p2, forest)  # p2 taps their land during p1's turn
    eng.rules.put_triggers_on_stack()
    assert eng.state.pending_choice is None, "reflexive — no target choice"
    eng.resolve_until_stable()
    eng.rules.check_state_based_actions()

    assert forest not in eng.state.battlefield
    assert forest in p2.graveyard


def test_price_of_glory_leaves_a_land_tapped_on_its_controllers_own_turn():
    eng = _engine()  # p1's turn
    _price_of_glory(eng, controller="p1")
    p1 = eng.state.player_by_id("p1")
    forest = _forest("p1")
    eng.state.add_to_battlefield(forest)

    eng.tap_for_mana(p1, forest)  # p1 taps their own land on their own turn
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    eng.rules.check_state_based_actions()

    assert forest in eng.state.battlefield, "it IS that player's turn — no destroy"


def test_price_of_glory_ignores_a_nonland_mana_source():
    eng = _engine()  # p1's turn
    _price_of_glory(eng, controller="p1")
    p2 = eng.state.player_by_id("p2")
    dork = _mana_dork("p2")
    eng.state.add_to_battlefield(dork)

    eng.tap_for_mana(p2, dork)  # a creature, not a land
    placed = eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    eng.rules.check_state_based_actions()

    assert placed == 0
    assert dork in eng.state.battlefield


def test_price_of_glory_does_not_fire_on_a_plain_tap_cost():
    """The trigger is TAPPED_FOR_MANA, not TAPPED — tapping a land for a
    non-mana reason must not destroy it."""
    eng = _engine()  # p1's turn
    _price_of_glory(eng, controller="p1")
    forest = _forest("p2")
    eng.state.add_to_battlefield(forest)

    eng.rules.set_tapped(forest, True)  # plain tap, no mana produced
    placed = eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    eng.rules.check_state_based_actions()

    assert placed == 0
    assert forest in eng.state.battlefield

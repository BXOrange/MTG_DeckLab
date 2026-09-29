"""PAR-119 (d) — "whenever `<a player>` taps `<a land>` for mana, …" bodies.

RULE 605.1b: a triggered ability that triggers off a mana ability and adds mana is itself
a mana ability — it resolves at once. "One mana of any type that land produced" is read
off the firing `TAPPED_FOR_MANA` event's ``produced`` (`mirror_produced_mana`), and "that
player" is whoever tapped the land. "That land doesn't untap …" names the firing event's
land, not an earlier target.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.services.card_database import CardDatabase

FLARE = ("Whenever a player taps a land for mana, that player adds one mana of any type "
         "that land produced.")
WAKE = "Whenever you tap a land for mana, add one mana of any type that land produced."


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _bf(state, card, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _land(state, name="Forest", owner="p1", supertype="Basic "):
    return _bf(state, Card(id=f"{name}-{owner}", name=name, type_line=f"{supertype}Land — {name}",
                           is_land=True), owner)


def _listener(state, oracle, owner="p1"):
    card = Card(id="Listener", name="Listener", type_line="Enchantment", oracle_text=oracle)
    assert parse_oracle(card).modeled, parse_oracle(card).unclaimed
    return _bf(state, card, owner)


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


def test_that_player_adds_names_the_tapping_player():
    specs = match_clause("that player adds 1 mana of any type that land produced")
    assert [(s.type, s.params) for s in specs] == [
        ("mirror_produced_mana", {"count": 1, "player": {"of": "event_player", "as": "controller"}}),
    ]


def test_add_is_the_abilitys_controller():
    specs = match_clause("add 1 mana of any type that land produced")
    assert [(s.type, s.params) for s in specs] == [("mirror_produced_mana", {"count": 1})]


@pytest.mark.parametrize("oracle", [FLARE, WAKE,
                                    "Whenever a player taps a basic land for mana, that player "
                                    "adds one mana of any type that land produced."])
def test_the_trigger_is_a_mana_ability(oracle):
    card = Card(id="X", name="X", type_line="Enchantment", oracle_text=oracle)
    result = parse_oracle(card)
    assert result.modeled
    [spec] = [s for s in result.specs if s.ability_kind == "triggered"]
    assert spec.trigger.get("mana_ability") is True


def test_a_non_mana_body_is_not_a_mana_ability():
    card = Card(id="X", name="X", type_line="Enchantment",
                oracle_text="Whenever an opponent taps a land for mana, that land doesn't untap "
                            "during its controller's next untap step.")
    result = parse_oracle(card)
    assert result.modeled
    [spec] = [s for s in result.specs if s.ability_kind == "triggered"]
    assert not spec.trigger.get("mana_ability")


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------


def _pool(engine, pid):
    return engine.state.player_by_id(pid).mana_pool.pool


def test_mana_flare_doubles_the_tapping_players_mana():
    engine = _engine()
    _listener(engine.state, FLARE)
    island = _land(engine.state, "Island", owner="p2")
    engine.tap_for_mana(engine.state.player_by_id("p2"), island)
    engine.resolve_until_stable()
    assert _pool(engine, "p2").get("U") == 2
    assert sum(_pool(engine, "p1").values()) == 0


def test_mirraris_wake_only_doubles_your_own_lands():
    engine = _engine()
    _listener(engine.state, WAKE)
    forest = _land(engine.state, "Forest")
    theirs = _land(engine.state, "Island", owner="p2")
    engine.tap_for_mana(engine.state.player_by_id("p1"), forest)
    engine.tap_for_mana(engine.state.player_by_id("p2"), theirs)
    engine.resolve_until_stable()
    assert _pool(engine, "p1").get("G") == 2
    assert _pool(engine, "p2").get("U") == 1


def test_a_basic_land_filter_skips_a_nonbasic_land():
    engine = _engine()
    _listener(engine.state, "Whenever a player taps a basic land for mana, that player adds one "
                            "mana of any type that land produced.")
    nonbasic = _land(engine.state, "Forest", supertype="")
    engine.tap_for_mana(engine.state.player_by_id("p1"), nonbasic)
    engine.resolve_until_stable()
    assert _pool(engine, "p1").get("G") == 1


def test_that_land_does_not_untap():
    engine = _engine()
    _listener(engine.state, "Whenever an opponent taps a land for mana, that land doesn't untap "
                            "during its controller's next untap step.")
    theirs = _land(engine.state, "Island", owner="p2")
    mine = _land(engine.state, "Forest")
    engine.tap_for_mana(engine.state.player_by_id("p2"), theirs)
    engine.tap_for_mana(engine.state.player_by_id("p1"), mine)
    engine.resolve_until_stable()
    assert theirs.skip_next_untap is True
    assert not getattr(mine, "skip_next_untap", False)


# ---------------------------------------------------------------------------
# Real cards
# ---------------------------------------------------------------------------


@pytest.mark.full_cache
@pytest.mark.parametrize("name", [
    "Mana Flare", "Heartbeat of Spring", "Dictate of Karametra", "Zhur-Taa Ancient",
    "Mirari's Wake", "Zendikar Resurgent", "Lavaleaper", "Vorinclex, Voice of Hunger",
    "Winter's Night",
])
def test_real_cards_are_modeled(name):
    assert parse_oracle(CardDatabase(DB_PATH).get_card(name)).modeled

"""Star Trek singleton batch G: real casting, cost payment and search choices."""
import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.star_trek import cast, game, vanilla


def _permanent(engine, player_id, name, type_line):
    obj = GameObject(Card(id=name, name=name, type_line=type_line,
                          is_land="Land" in type_line),
                     owner_id=player_id, zone=Zone.BATTLEFIELD)
    obj.controller_id = player_id
    engine.state.add_to_battlefield(obj)
    return obj


@pytest.mark.parametrize("name", ["Rite of Oblivion", "70,000 Light-Years from Home"])
def test_specs_are_fresh_and_bind(name):
    engine, p1, _ = game(name)
    card = p1.hand[0]
    first, second = specs_for(card.card), specs_for(card.card)
    assert first and first[0] is not second[0]
    assert first[0].effects[0] is not second[0].effects[0]
    for spec in first:
        spec.validate()
    assert card.spell_effects


def test_rite_pays_noncreature_cost_then_exiles_and_flashes_back():
    engine, p1, p2 = game("Rite of Oblivion")
    spell = p1.hand[0]
    rock = _permanent(engine, "p1", "Rock", "Artifact")
    target = vanilla(engine, "p2")
    p1.mana_pool.add_many({"W": 2, "B": 2, "C": 2})
    engine.cast_spell(p1, spell, targets=[target], sacrifice_choice=rock.instance_id)
    assert rock in p1.graveyard and target.zone == Zone.BATTLEFIELD
    engine.resolve_until_stable()
    assert target in p2.exile and spell in p1.graveyard
    second_cost = vanilla(engine, "p1", "Payment")
    second_target = _permanent(engine, "p2", "Enchantment", "Enchantment")
    engine.cast_spell(p1, spell, targets=[second_target], sacrifice_choice=second_cost.instance_id)
    assert spell.cast_via_flashback and second_cost in p1.graveyard
    engine.resolve_until_stable()
    assert spell in p1.exile and second_target in p2.exile


@pytest.mark.parametrize("bad_cost", ["land", "opponent"])
def test_rite_rejects_illegal_sacrifice_without_spending_mana(bad_cost):
    engine, p1, p2 = game("Rite of Oblivion")
    spell = p1.hand[0]
    land = _permanent(engine, "p1", "Forest", "Basic Land")
    opponent = vanilla(engine, "p2")
    p1.mana_pool.add_many({"W": 1, "B": 1})
    before = p1.mana_pool.total()
    with pytest.raises(ValueError):
        engine.cast_spell(p1, spell, targets=[opponent],
                          sacrifice_choice=(land if bad_cost == "land" else opponent).instance_id)
    assert p1.mana_pool.total() == before
    assert spell in p1.hand and land.zone == opponent.zone == Zone.BATTLEFIELD


@pytest.mark.parametrize("type_line", ["Creature", "Artifact — Spacecraft"])
@pytest.mark.parametrize("clone", [False, True])
def test_light_years_searches_for_targets_controller_reveals_and_puts_in_hand(type_line, clone):
    engine, p1, p2 = game("70,000 Light-Years from Home")
    target = (vanilla(engine, "p2") if type_line == "Creature"
              else _permanent(engine, "p2", "Ship", type_line))
    # The target's controller, rather than its owner, receives the search.
    target.owner_id = "p1"
    basic = GameObject(Card(id="basic", name="Forest", type_line="Basic Land — Forest", is_land=True),
                       owner_id="p2", zone=Zone.LIBRARY)
    p2.library.append(basic)
    cast(engine, p1, p1.hand[0], targets=[target])
    assert target in p1.exile
    if clone:
        engine = GameEngine(engine.state.clone())
        p2 = engine.state.player_by_id("p2")
        basic = next(o for o in p2.library if o.instance_id == basic.instance_id)
    choice = engine.state.pending_choice
    assert choice and choice["player_id"] == "p2", choice
    assert choice["kind"] == "exile_controller_search"
    engine.resolve_pending_choice("search")
    choice = engine.state.pending_choice
    option = next(o for o in choice["options"] if str(basic.instance_id) in str(o["id"]))
    engine.resolve_pending_choice(option["id"])
    engine.resolve_until_stable()
    assert basic in p2.hand and basic not in p2.library
    assert any(e.type == EventType.REVEAL and e.get("instance_id") == basic.instance_id
               for e in engine.state.events_this_turn())


def test_light_years_controller_can_decline_search(monkeypatch):
    engine, p1, p2 = game("70,000 Light-Years from Home")
    target = vanilla(engine, "p2")
    basic = GameObject(Card(id="basic", name="Forest", type_line="Basic Land — Forest", is_land=True),
                       owner_id="p2", zone=Zone.LIBRARY)
    p2.library.append(basic)
    cast(engine, p1, p1.hand[0], targets=[target])
    choice = engine.state.pending_choice
    assert choice
    assert any(o["id"] == "decline" for o in choice["options"]), choice
    shuffles = []
    monkeypatch.setattr(engine.rules, "shuffle_library", lambda player: shuffles.append(player.id))
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert target in p2.exile and basic in p2.library and not p2.hand
    assert not shuffles


def test_light_years_fizzles_without_search_when_only_target_is_gone():
    engine, p1, p2 = game("70,000 Light-Years from Home")
    target = vanilla(engine, "p2")
    p1.mana_pool.add_many({"W": 1, "C": 1})
    engine.cast_spell(p1, p1.hand[0], targets=[target])
    engine.rules.destroy(target)
    engine.resolve_until_stable()
    assert target in p2.graveyard and engine.state.pending_choice is None


def test_winds_of_abandon_retains_tapped_battlefield_search_default():
    engine, p1, p2 = game("Winds of Abandon")
    target = vanilla(engine, "p2")
    basic = GameObject(Card(id="basic", name="Forest", type_line="Basic Land — Forest", is_land=True),
                       owner_id="p2", zone=Zone.LIBRARY)
    p2.library.append(basic)
    cast(engine, p1, p1.hand[0], targets=[target])
    choice = engine.state.pending_choice
    assert choice and choice["player_id"] == "p2", choice
    option = next(o for o in choice["options"] if str(basic.instance_id) in str(o["id"]))
    engine.resolve_pending_choice(option["id"])
    engine.resolve_until_stable()
    assert target in p2.exile
    assert basic.zone == Zone.BATTLEFIELD and basic.tapped

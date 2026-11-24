"""Quark, Humble Proprietor: a standing "can't sacrifice your Treasure tokens" plus a Treasure each upkeep."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.mana_potential import find_tap_plan
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.services.token_database import synthesize_token_card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.star_trek import game

NAME = "Quark, Humble Proprietor"
ORACLE = (
    "You can't sacrifice Treasure tokens.\n"
    "At the beginning of each upkeep, create a Treasure token. "
    "(It's an artifact with \"{T}, Sacrifice this token: Add one mana of any color.\")"
)
TREASURE_COST = 1  # one generic mana, payable only by the Treasure in these tests


def _quark():
    return Card(id="quark", name=NAME, type_line="Legendary Creature — Ferengi Rogue", is_creature=True,
                is_legendary=True, power=1, toughness=2, mana_cost_string="{2}{R}", converted_mana_cost=3,
                oracle_text=ORACLE)


def _board():
    engine, p1, p2 = game()
    quark = GameObject(_quark(), owner_id="p1", zone=Zone.BATTLEFIELD)
    quark.controller_id = "p1"
    bind_from_catalogue(quark)
    engine.state.add_to_battlefield(quark)
    return engine, p1, p2, quark


def _treasure(engine, owner):
    """A real Treasure token made by the engine's own token path (so it carries its real mana ability)."""
    (token,) = engine.rules.create_token(owner, synthesize_token_card(
        "Treasure", subtypes=["Treasure"], is_artifact=True,
        oracle_text="{T}, Sacrifice this artifact: Add one mana of any color."))
    engine.recompute_continuous_effects()
    return token


def test_specs_are_fresh_valid_and_bind():
    first, second = specs_for(_quark()), specs_for(_quark())
    assert first[0] is not second[0] and sorted(s.ability_kind for s in first) == ["static", "triggered"]
    for spec in first:
        spec.validate()
    engine, *_ = _board()
    quark = next(o for o in engine.state.battlefield if o.name == NAME)
    assert quark.triggered_abilities and quark.static_effects


def test_own_treasure_cannot_be_sacrificed_for_mana():
    engine, p1, p2, quark = _board()
    treasure = _treasure(engine, "p1")
    assert treasure.cant_be_sacrificed_this_turn
    with pytest.raises(ValueError):
        engine.tap_for_mana(p1, treasure)
    assert treasure.zone == Zone.BATTLEFIELD and not treasure.tapped and p1.mana_pool.total() == 0


def test_auto_tap_planning_never_counts_the_locked_treasure():
    engine, p1, p2, quark = _board()
    _treasure(engine, "p1")
    assert find_tap_plan(engine, p1, ManaCost.parse("{1}")) is None


def test_opponents_treasure_is_unaffected():
    engine, p1, p2, quark = _board()
    foe_treasure = _treasure(engine, "p2")
    assert not foe_treasure.cant_be_sacrificed_this_turn
    engine.tap_for_mana(p2, foe_treasure)
    assert foe_treasure.zone != Zone.BATTLEFIELD and p2.mana_pool.total() == TREASURE_COST


def test_other_artifacts_and_non_treasure_tokens_can_still_be_sacrificed():
    engine, p1, p2, quark = _board()
    (token,) = engine.rules.create_token("p1", synthesize_token_card("Clue", subtypes=["Clue"], is_artifact=True))
    engine.recompute_continuous_effects()
    assert not token.cant_be_sacrificed_this_turn
    engine.rules.sacrifice(p1, "artifact", 1)
    engine.resolve_until_stable()
    assert token.zone != Zone.BATTLEFIELD


def test_sacrifice_effect_skips_the_locked_treasure():
    engine, p1, p2, quark = _board()
    treasure = _treasure(engine, "p1")
    engine.rules.sacrifice(p1, "artifact", 1)
    engine.resolve_until_stable()
    assert treasure.zone == Zone.BATTLEFIELD


def test_treasure_is_free_again_once_quark_leaves():
    engine, p1, p2, quark = _board()
    treasure = _treasure(engine, "p1")
    assert treasure.cant_be_sacrificed_this_turn
    engine.rules.destroy(quark)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert not treasure.cant_be_sacrificed_this_turn
    engine.tap_for_mana(p1, treasure)
    assert treasure.zone != Zone.BATTLEFIELD and p1.mana_pool.total() == TREASURE_COST


def test_each_upkeep_creates_a_treasure_for_quarks_controller():
    from tests.support.star_trek import advance_to
    engine, p1, p2 = game(via_steps=True, stop_at="upkeep")
    quark = GameObject(_quark(), owner_id="p1", zone=Zone.BATTLEFIELD)
    quark.controller_id = "p1"
    bind_from_catalogue(quark)
    engine.state.add_to_battlefield(quark)
    seen = []
    for _ in range(60):  # bounded walk: through both players' upkeeps
        engine.advance_step()
        engine.resolve_until_stable()
        if engine.state.current_step == "upkeep":
            seen.append(engine.state.active_player.id)
            if len(seen) == 2:
                break
    treasures = [o for o in engine.state.battlefield if o.name == "Treasure"]
    assert sorted(seen) == ["p1", "p2"] and len(treasures) == 2 and all(t.controller_id == "p1" for t in treasures)

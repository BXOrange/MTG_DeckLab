"""Mox Opal's Metalcraft gates manual mana, offers and auto-tap potential."""
import pytest

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game import mana_potential
from mtg_analyzer.game.mana_abilities import mana_abilities_for, parse_mana_abilities
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _artifact(engine, name, owner="p1", text=""):
    card = Card(id=name, name=name, type_line="Legendary Artifact" if name == "Mox Opal" else "Artifact",
                oracle_text=text)
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    engine.state.add_to_battlefield(obj)
    return obj


def _setup():
    engine = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    opal = _artifact(engine, "Mox Opal", text=(
        "Metalcraft — {T}: Add one mana of any color. Activate only if you control three or more artifacts."
    ))
    return engine, engine.state.player_by_id("p1"), opal


@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_metalcraft_threshold_includes_opal_itself(count):
    engine, player, opal = _setup()
    for index in range(count - 1):
        _artifact(engine, f"Own {index}")
    for index in range(3):
        _artifact(engine, f"Opponent {index}", owner="p2")
    parsed = parse_mana_abilities(opal.card)
    assert len(parsed) == 1
    assert parsed[0].cost.activation_condition
    offered = [a for a in engine.legal_actions(player) if a["type"] == "tap_for_mana"]
    assert bool(offered) == (count >= 3)
    assert bool(mana_abilities_for(opal, engine.state)[0].options) == (count >= 3)
    assert mana_potential.max_potential_total(engine, player) == (1 if count >= 3 else 0)
    if count < 3:
        with pytest.raises(ValueError):
            engine.tap_for_mana(player, opal)
        assert not opal.tapped
        assert player.mana_pool.total() == 0
    else:
        engine.tap_for_mana(player, opal)
        assert opal.tapped
        assert player.mana_pool.total() == 1


def test_losing_control_of_third_artifact_disables_mana_immediately():
    engine, player, opal = _setup()
    _artifact(engine, "Second")
    third = _artifact(engine, "Third")
    assert mana_potential.max_potential_total(engine, player) == 1
    third.controller_id = "p2"
    assert mana_potential.max_potential_total(engine, player) == 0
    with pytest.raises(ValueError):
        engine.tap_for_mana(player, opal)
    assert not opal.tapped


def test_unknown_activation_condition_does_not_become_unconditional_mana():
    card = Card(id="Unknown", name="Unknown", type_line="Artifact", oracle_text=(
        "{T}: Add {G}. Activate only if an unmodeled condition holds."
    ))
    assert parse_mana_abilities(card) == []


def test_conditional_ability_keeps_its_index_next_to_unconditional_mana():
    engine, player, opal = _setup()
    opal.card.oracle_text = (
        "{T}: Add {C}.\n{T}: Add {G}. Activate only if you control three or more artifacts."
    )
    abilities = mana_abilities_for(opal, engine.state)
    assert len(abilities) == 2
    assert abilities[0].options == [{"C": 1}]
    assert abilities[1].options == []
    _artifact(engine, "Second")
    _artifact(engine, "Third")
    assert mana_abilities_for(opal, engine.state)[1].options == [{"G": 1}]
    engine.tap_for_mana(player, opal, ability_index=1)
    assert player.mana_pool.total() == 1

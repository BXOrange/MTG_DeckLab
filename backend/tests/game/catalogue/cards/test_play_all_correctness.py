"""Live regressions for the PLAY-ALL card correctness follow-ups."""
import pytest
from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.catalogue import battlefield_object


def _game():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_hand=0, starting_life=20)
    engine.begin_turn()
    engine.state.current_step = "main1"
    return engine, engine.state.players[0], engine.state.players[1]


def test_magda_creates_only_one_tapped_treasure_for_real_crimes_in_a_turn():
    engine, p1, p2 = _game()
    magda = GameObject(CardDatabase(DB_PATH).get_card("Magda, the Hoardmaster"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(magda)
    engine.state.add_to_battlefield(magda)
    for i in range(2):
        spell = GameObject(Card(id=str(i), name="Ping", type_line="Instant", is_instant=True,
                               oracle_text="Deal 1 damage to target player."), owner_id="p1", zone=Zone.HAND)
        bind_from_catalogue(spell)
        p1.hand.append(spell)
        engine.cast_spell(p1, spell, targets=[p2])
        engine.resolve_until_stable()
    treasures = [o for o in engine.state.battlefield if o.name == "Treasure"]
    assert len(treasures) == 1 and treasures[0].tapped


def test_jaya_requires_my_legendary_creature_or_planeswalker():
    engine, p1, p2 = _game()
    spell = GameObject(CardDatabase(DB_PATH).get_card("Jaya's Immolating Inferno"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    p1.mana_pool.add_many({"R": 5})
    assert not engine.can_cast(p1, spell, targets=[p2], x=1)
    legend = battlefield_object(engine, "p2", "Legend", "Legendary Creature", is_creature=True,
                                is_legendary=True, power=2, toughness=2)
    assert not engine.can_cast(p1, spell, targets=[p2], x=1)
    legend.controller_id = "p1"
    assert engine.can_cast(p1, spell, targets=[p2], x=1)
    engine.cast_spell(p1, spell, targets=[p2], x=1)
    engine.resolve_until_stable()
    assert p2.life == 19


@pytest.mark.parametrize("kind", ["Instant", "Sorcery"])
def test_legendary_spell_gate_applies_without_catalogue_reminder_text(kind):
    engine, p1, p2 = _game()
    spell = GameObject(Card(id=kind, name="Legendary study", type_line=f"Legendary {kind}",
                            is_instant=kind == "Instant", is_sorcery=kind == "Sorcery",
                            oracle_text="Draw a card."), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    assert getattr(spell, "cast_condition", None) is None
    assert not engine.can_cast(p1, spell)
    battlefield_object(engine, "p1", "Legendary rock", "Legendary Artifact", is_legendary=True)
    assert not engine.can_cast(p1, spell)
    battlefield_object(engine, "p1", "Walker", "Legendary Planeswalker", is_legendary=True)
    assert engine.can_cast(p1, spell)

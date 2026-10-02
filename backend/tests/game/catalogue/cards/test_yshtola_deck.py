"""Hand-authored cards of the saved "yshtola" deck (PLAY-ALL Step 2)."""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import is_registered
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.catalogue import battlefield_object, two_player_game


def _spell(player, name, type_line, cost, cmc, colors):
    card = Card(
        id=name, name=name, type_line=type_line, mana_cost_string=cost,
        converted_mana_cost=cmc, color_identity=set(colors),
        is_creature="creature" in type_line.lower(),
    )
    obj = GameObject(card, owner_id=player.id, zone=Zone.HAND)
    bind_from_catalogue(obj)
    player.add_to_zone(obj, Zone.HAND)
    return obj


def test_stormscape_familiar_discounts_white_and_black_spells_only():
    engine, player = two_player_game()
    familiar = battlefield_object(
        engine, player.id, "Stormscape Familiar", "Creature — Bird", is_creature=True, power=1, toughness=1,
    )
    bind_from_catalogue(familiar)
    assert is_registered("Stormscape Familiar")
    white = _spell(player, "White Spell", "Sorcery", "{2}{W}", 3, "W")
    black = _spell(player, "Black Spell", "Creature — Bear", "{2}{B}", 3, "B")
    green = _spell(player, "Green Spell", "Sorcery", "{2}{G}", 3, "G")
    assert continuous.cost_reduction_for(engine.state, player, white)[0] == 1
    assert continuous.cost_reduction_for(engine.state, player, black)[0] == 1
    assert continuous.cost_reduction_for(engine.state, player, green)[0] == 0

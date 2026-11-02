"""Hagra Mauling // Hagra Broodpit (hand-authored)."""

import pytest

from mtg_analyzer.game import continuous
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game
from tests.support.catalogue import battlefield_object

NAME = "Hagra Mauling // Hagra Broodpit"


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    assert [s.ability_kind for s in first][:2] == ["static", "spell_effect"]


@pytest.mark.parametrize("opponent_land, reduced", [
    ("Plains", False),          # a basic land: no reduction
    ("Stone Quarry", True),     # nonbasic only: the opponent controls no basic land
])
def test_cost_reduction_needs_an_opponent_with_no_basic_lands(opponent_land, reduced):
    engine = _game()
    hagra = _card(engine, NAME, zone=Zone.HAND)
    if opponent_land == "Plains":
        _card(engine, "Plains", player="p2")
    else:
        battlefield_object(engine, "p2", "Stone Quarry", "Land", is_land=True)
    # The spell's own printed cost static, read off the card in hand (`self_cost_reduction_for`, not the battlefield scan).
    net, _ = continuous.self_cost_reduction_for(hagra, engine.state, "p1")
    assert net == (1 if reduced else 0)


def test_destroy_resolves_on_the_chosen_creature():
    engine = _game()
    hagra = _card(engine, NAME, zone=Zone.HAND)
    victim = battlefield_object(engine, "p2", "Victim", "Creature — Bear", is_creature=True, power=2, toughness=2)
    caster = engine.state.player_by_id("p1")
    caster.mana_pool.add("B", 4)
    engine.rules.cast_spell(caster, hagra, targets=[victim])
    engine.resolve_until_stable()
    assert victim.zone == Zone.GRAVEYARD
    assert hagra.zone == Zone.GRAVEYARD

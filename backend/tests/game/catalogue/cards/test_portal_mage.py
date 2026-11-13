"""Portal Mage (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Portal Mage'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first][:1] == ['triggered']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.triggered_abilities


@pytest.mark.parametrize("answer", ["player:p3", "decline"])
def test_end_to_end(answer):
    engine = _game(3)
    player, opponent, chooser = engine.state.players
    attacker = _card(engine, "Grizzly Bears")
    attacker.summoning_sick = False
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(player, [{"attacker": attacker, "defender": {"kind": "player", "id": "p2"}}])
    mage = _card(engine, NAME, player="p3", zone=Zone.HAND)
    chooser.mana_pool.add_many({"U": 1, "C": 2})
    engine.cast_spell(chooser, mage)
    engine.resolve_until_stable()
    if engine.state.pending_choice["kind"] == "trigger_target":
        engine.resolve_pending_choice(str(attacker.instance_id))
        engine.resolve_until_stable()
    assert engine.state.pending_choice["kind"] == "reselect_attack"
    assert engine.state.pending_choice["player_id"] == "p3"
    engine.resolve_pending_choice(answer)
    engine.resolve_until_stable()
    assert attacker.combat_defender["id"] == ("p3" if answer != "decline" else "p2")


def test_cast_outside_declare_attackers_does_not_redirect():
    engine = _game(3)
    chooser = engine.state.players[2]
    mage = _card(engine, NAME, player="p3", zone=Zone.HAND)
    chooser.mana_pool.add_many({"U": 1, "C": 2})
    engine.cast_spell(chooser, mage)
    engine.resolve_until_stable()
    assert not engine.state.pending_choice

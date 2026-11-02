"""Warden of the Grove (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Warden of the Grove'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first] == ['triggered', 'triggered']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.triggered_abilities


@pytest.mark.parametrize("branch", ["counters", "token"])
def test_end_to_end(branch):
    engine = _game()
    warden = _card(engine, NAME)
    engine.rules.add_counters(warden, 2, "+1/+1")
    engine.rules.add_counters(warden, 1, "shield")
    creature = _card(engine, "Grizzly Bears", zone=Zone.HAND)
    engine.rules.cast_without_paying(engine.state.players[0], creature)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert engine.state.pending_choice["kind"] == "endure"
    assert engine.state.pending_choice["amount"] == 3
    engine.resolve_pending_choice(branch)
    engine.resolve_until_stable()
    if branch == "counters":
        assert creature.counters.get("+1/+1") == 3
    else:
        spirits = [o for o in engine.state.battlefield if o.is_token and "Spirit" in o.card.type_line]
        assert len(spirits) == 1 and spirits[0].power == spirits[0].toughness == 3


def test_zero_counters_and_token_or_enemy_entry_do_not_endure():
    from mtg_analyzer.services.token_database import synthesize_token_card
    engine = _game()
    warden = _card(engine, NAME)
    creature = _card(engine, "Grizzly Bears", zone=Zone.HAND)
    engine.rules.cast_without_paying(engine.state.players[0], creature)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert not engine.state.pending_choice
    assert not creature.counters
    engine.rules.add_counters(warden, 2, "+1/+1")
    engine.rules.create_token("p1", synthesize_token_card("Bear", power=2, toughness=2), 1)
    enemy = _card(engine, "Grizzly Bears", player="p2", zone=Zone.HAND)
    engine.rules.cast_without_paying(engine.state.players[1], enemy)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert not engine.state.pending_choice
    assert not enemy.counters

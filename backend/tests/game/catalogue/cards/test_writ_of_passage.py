"""Writ of Passage (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Writ of Passage'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    assert [s.ability_kind for s in first][:2] == ['triggered', 'activated']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.activated_abilities


def _attack_with_enchanted(power):
    from mtg_analyzer.game.card_catalogue.w.writ_of_passage import WRIT_MAX_POWER  # noqa: F401
    from tests.support.catalogue import battlefield_object

    engine = _game()
    p1, p2 = engine.state.players
    bear = battlefield_object(engine, "p1", "Bear", "Creature — Bear", power=power, toughness=2, is_creature=True)
    bear.summoning_sick = False
    writ = _card(engine, NAME)
    writ.attached_to = bear.instance_id
    engine.state.current_phase, engine.state.current_step = "combat", "declare_attackers"
    engine.declare_attackers(p1, [{"attacker": bear, "defender": engine.legal_defenders_for(p1)[0]}])
    engine.resolve_until_stable()
    return bear


def test_end_to_end():
    # RULE 603.4: power 2 -> condition holds -> attacker can't be blocked this turn.
    assert _attack_with_enchanted(2).temp_unblockable is True


def test_power_three_does_not_trigger():
    assert not _attack_with_enchanted(3).temp_unblockable

"""Atomic Microsizer (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Atomic Microsizer'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    assert [s.ability_kind for s in first][:2] == ['static', 'triggered']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.static_effects


def _attack(decline_target=False):
    from mtg_analyzer.game import continuous
    from tests.support.catalogue import battlefield_object

    engine = _game()
    p1, p2 = engine.state.players
    knight = battlefield_object(engine, "p1", "Knight", "Creature — Knight", power=4, toughness=4, is_creature=True)
    knight.summoning_sick = False
    ogre = battlefield_object(engine, "p2", "Ogre", "Creature — Ogre", power=5, toughness=5, is_creature=True)
    equipment = _card(engine, NAME)
    equipment.attached_to = knight.instance_id
    engine.state.current_phase, engine.state.current_step = "combat", "declare_attackers"
    engine.declare_attackers(p1, [{"attacker": knight, "defender": engine.legal_defenders_for(p1)[0]}])
    engine.resolve_until_stable()  # the attack trigger opens its "up to one" target choice
    choice = engine.state.pending_choice
    assert choice and choice["kind"] == "trigger_target"
    pick = "decline" if decline_target else next(str(o["id"]) for o in choice["options"] if o.get("label") == "Ogre")
    engine.resolve_pending_choice(pick)
    engine.resolve_until_stable()
    continuous.recompute(engine.state)
    return knight, ogre


def test_end_to_end():
    # RULE 613.4b: the chosen creature becomes a base 1/1 and can't be blocked this turn.
    knight, ogre = _attack()
    assert ogre.temp_unblockable
    assert (ogre.power, ogre.toughness) == (1, 1)
    # The equipped creature's own +1/+0 (static anthem) is untouched.
    assert (knight.power, knight.toughness) == (5, 4)


def test_declining_the_target_changes_nothing():
    knight, ogre = _attack(decline_target=True)
    assert not ogre.temp_unblockable
    assert (ogre.power, ogre.toughness) == (5, 5)

"""Open into Wonder (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Open into Wonder'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    assert [s.ability_kind for s in first] == ['spell_effect']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.spell_effects


def _cast_with_x(x, n_creatures=3, mana=6):
    from tests.support.catalogue import battlefield_object

    engine = _game()
    p1 = engine.state.player_by_id("p1")
    spell = _card(engine, NAME, zone=Zone.HAND)
    creatures = [
        battlefield_object(engine, "p1", f"C{n}", "Creature — Bear", power=2, toughness=2, is_creature=True)
        for n in range(n_creatures)
    ]
    for c in creatures:
        c.summoning_sick = False
    p1.mana_pool.add("U", mana)
    engine.state.current_step = "main1"
    return engine, p1, spell, creatures


def test_end_to_end():
    # RULE 107.3c: X=2 -> exactly the two chosen creatures are unblockable and get the draw trigger.
    engine, p1, spell, creatures = _cast_with_x(2)
    engine.cast_spell(p1, spell, targets=creatures[:2], x=2)
    engine.resolve_until_stable()
    assert [c.temp_unblockable for c in creatures] == [True, True, False]
    hand_before = len(p1.hand)
    engine.state.current_phase, engine.state.current_step = "combat", "declare_attackers"
    engine.declare_attackers(p1, [{"attacker": creatures[0], "defender": engine.legal_defenders_for(p1)[0]}])
    engine.resolve_until_stable()
    engine.state.current_step = "declare_blockers"
    engine.declare_blockers(engine.state.player_by_id("p2"), {})
    engine._deal_combat_damage_step(False)
    engine.resolve_until_stable()
    assert len(p1.hand) == hand_before + 1


def test_ungranted_creature_does_not_draw():
    engine, p1, spell, creatures = _cast_with_x(1)
    engine.cast_spell(p1, spell, targets=creatures[:1], x=1)
    engine.resolve_until_stable()
    hand_before = len(p1.hand)
    engine.state.current_phase, engine.state.current_step = "combat", "declare_attackers"
    engine.declare_attackers(p1, [{"attacker": creatures[2], "defender": engine.legal_defenders_for(p1)[0]}])
    engine.resolve_until_stable()
    engine.state.current_step = "declare_blockers"
    engine.declare_blockers(engine.state.player_by_id("p2"), {})
    engine._deal_combat_damage_step(False)
    engine.resolve_until_stable()
    assert len(p1.hand) == hand_before

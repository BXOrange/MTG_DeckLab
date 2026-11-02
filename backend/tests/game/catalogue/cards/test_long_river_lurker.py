"""Long River Lurker (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Long River Lurker'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    assert [s.ability_kind for s in first][:2] == ['static', 'triggered']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.static_effects


def _answer(engine, label=None, option=None):
    choice = engine.state.pending_choice
    assert choice is not None
    if option is not None:
        engine.resolve_pending_choice(option)
        return choice
    engine.resolve_pending_choice(next(str(o["id"]) for o in choice["options"] if o.get("label") == label))
    return choice


def _cast_and_attack(accept=True, second_creature=False):
    from tests.support.catalogue import battlefield_object

    engine = _game()
    p1, p2 = engine.state.players
    bear = battlefield_object(engine, "p1", "Bear", "Creature — Bear", power=2, toughness=2, is_creature=True)
    bear.summoning_sick = False
    other = battlefield_object(engine, "p1", "Other", "Creature — Bear", power=2, toughness=2, is_creature=True)
    other.summoning_sick = False
    lurker = _card(engine, NAME, zone=Zone.HAND)
    engine.state.current_phase, engine.state.current_step = "main", "main1"
    p1.mana_pool.add("U", 5)
    engine.cast_spell(p1, lurker)
    engine.resolve_until_stable()  # Lurker resolves; its ETB asks for a target
    _answer(engine, "Bear")
    engine.resolve_until_stable()
    assert bear.temp_unblockable
    assert not other.temp_unblockable
    visit = bear.zone_incarnation
    engine.state.current_phase, engine.state.current_step = "combat", "declare_attackers"
    engine.declare_attackers(p1, [{"attacker": bear, "defender": engine.legal_defenders_for(p1)[0]},
                                  {"attacker": other, "defender": engine.legal_defenders_for(p1)[0]}])
    engine.resolve_until_stable()
    engine.state.current_step = "declare_blockers"
    engine.declare_blockers(p2, {})
    engine._deal_combat_damage_step(False)
    engine.resolve_until_stable()
    return engine, p1, bear, other, visit


def test_end_to_end():
    # RULE 603.7a: only the chosen creature's combat damage triggers; accepting blinks it (RULE 400.7).
    engine, p1, bear, other, visit = _cast_and_attack()
    choice = engine.state.pending_choice
    assert choice is not None, "the 'you may exile it' choice should be pending"
    engine.resolve_pending_choice("yes" if any(o.get("id") == "yes" for o in choice.get("options", [])) else
                                  str(choice["options"][0]["id"]))
    engine.resolve_until_stable()
    assert bear.zone.name == "BATTLEFIELD"
    assert bear.zone_incarnation > visit
    assert not bear.attacking
    assert other.attacking  # the un-chosen attacker was never blinked


def test_declining_the_optional_exile_keeps_the_creature_in_play():
    engine, p1, bear, other, visit = _cast_and_attack()
    choice = engine.state.pending_choice
    assert choice is not None
    declines = [o for o in choice["options"] if o.get("id") in ("no", "decline")]
    assert declines, choice
    engine.resolve_pending_choice(str(declines[0]["id"]))
    engine.resolve_until_stable()
    assert bear.zone_incarnation == visit and bear.attacking

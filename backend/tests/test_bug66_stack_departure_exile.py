"""BUG-66 -- a spell cast from the graveyard with "exile instead" (Flashback RULE 702.34a, Beam me up RULE 702.196a)
is exiled whenever it leaves the stack, not only on resolution/counter: bounce effects, Buyback, library/exile moves.
Driven on real cached cards in a real engine."""

from __future__ import annotations

from mtg_analyzer.models.game.game_object import Zone
from tests.support.star_trek import PAYMENT_MANA, game, vanilla

FLASHBACK_COST = "{2}{U}"  # a granted Flashback cost (Snapcaster Mage-shaped), also paid for Buyback's {3} below


def _to_graveyard(player, obj):
    player.hand.remove(obj)
    player.add_to_zone(obj, Zone.GRAVEYARD)
    return obj


def _named(player, name):
    return next(o for o in player.hand if o.name == name)


def _fuel(player):
    player.mana_pool.add_many({"C": PAYMENT_MANA, "U": PAYMENT_MANA})


def _flashback_think_twice():
    """p1 with Think Twice cast from the graveyard (Flashback) and Unsubstantiate in hand; returns the spell on the stack."""
    engine, p1, p2 = game("Think Twice", "Unsubstantiate")
    think = _to_graveyard(p1, _named(p1, "Think Twice"))
    unsub = _named(p1, "Unsubstantiate")
    engine.state.temp_flashback_grants[think.instance_id] = FLASHBACK_COST
    _fuel(p1)
    engine.cast_spell(p1, think)
    assert think.cast_via_flashback and think in [i.obj for i in engine.state.stack]
    return engine, p1, think, unsub


def test_flashback_spell_bounced_off_the_stack_is_exiled_not_returned_to_hand():
    engine, p1, think, unsub = _flashback_think_twice()
    engine.cast_spell(p1, unsub, targets=[think])
    engine.resolve_until_stable()
    assert think in p1.exile and think not in p1.hand and think not in p1.graveyard


def test_beam_me_up_spell_bounced_off_the_stack_is_exiled_not_returned_to_hand():
    engine, p1, p2 = game("Energize", "Unsubstantiate")
    spell = _to_graveyard(p1, _named(p1, "Energize"))
    unsub = _named(p1, "Unsubstantiate")
    vanilla(engine, "p1", "Mine")
    theirs = vanilla(engine, "p2", "Theirs")
    _fuel(p1)
    engine.cast_spell(p1, spell, targets=[theirs])
    engine.cast_spell(p1, unsub, targets=[spell])
    engine.resolve_until_stable()
    assert spell in p1.exile and spell not in p1.hand and spell not in p1.graveyard


def test_move_spell_off_stack_and_counter_destinations_exile_a_flashback_spell():
    for destination in ("hand", "library_top", "library_bottom"):
        engine, p1, think, unsub = _flashback_think_twice()
        assert engine.rules.move_spell_off_stack(think, destination)
        assert think in p1.exile and think not in p1.hand and think not in p1.library, destination
    for destination in ("hand", "library_top"):
        engine, p1, think, unsub = _flashback_think_twice()
        engine.rules.counter_spell(think, destination=destination)
        assert think in p1.exile and think not in p1.hand and think not in p1.library, destination
    engine, p1, think, unsub = _flashback_think_twice()
    engine.rules.counter_spell(think, library_choice=True)
    assert think in p1.exile and think not in p1.library


def test_countered_flashback_spell_is_exiled():
    engine, p1, think, unsub = _flashback_think_twice()
    engine.rules.counter_spell(think)
    assert think in p1.exile and think not in p1.graveyard


def test_flashback_with_buyback_is_exiled_on_resolution():
    engine, p1, p2 = game("Capsize")
    capsize = _to_graveyard(p1, _named(p1, "Capsize"))
    target = vanilla(engine, "p2", "Theirs")
    engine.state.temp_flashback_grants[capsize.instance_id] = FLASHBACK_COST
    _fuel(p1)
    engine.cast_spell(p1, capsize, targets=[target], buyback=True)
    assert capsize.buyback_paid and capsize.cast_via_flashback
    engine.resolve_until_stable()
    assert target in p2.hand
    assert capsize in p1.exile and capsize not in p1.hand  # RULE 702.34a: exile instead of anywhere else


def test_flashback_spell_whose_target_vanished_is_still_exiled_with_buyback():
    engine, p1, p2 = game("Capsize")
    capsize = _to_graveyard(p1, _named(p1, "Capsize"))
    target = vanilla(engine, "p2", "Theirs")
    engine.state.temp_flashback_grants[capsize.instance_id] = FLASHBACK_COST
    _fuel(p1)
    engine.cast_spell(p1, capsize, targets=[target], buyback=True)
    engine.rules.return_to_hand(target)
    engine.resolve_until_stable()
    assert capsize in p1.exile and capsize not in p1.hand


def test_hand_cast_buyback_spell_still_returns_to_hand_and_bounce_still_works():
    engine, p1, p2 = game("Capsize", "Unsubstantiate")
    capsize, unsub = _named(p1, "Capsize"), _named(p1, "Unsubstantiate")
    target = vanilla(engine, "p2", "Theirs")
    _fuel(p1)
    engine.cast_spell(p1, capsize, targets=[target], buyback=True)
    engine.resolve_until_stable()
    assert capsize in p1.hand  # RULE 702.27a unchanged for a normal cast
    target = vanilla(engine, "p2", "Theirs Again")
    engine.cast_spell(p1, capsize, targets=[target])
    engine.cast_spell(p1, unsub, targets=[capsize])
    engine.resolve_until_stable()
    assert capsize in p1.hand and capsize not in p1.exile

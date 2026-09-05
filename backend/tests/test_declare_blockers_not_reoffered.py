"""Bug fix, 2026-09-05: RULE 509.1a's "declares no blocks" is itself a
complete, submittable answer — but `legal_actions` had no way to tell "this
defending player already declared blockers for this combat" apart from
"hasn't gone yet" once the answer was an empty assignment list, since an
empty block leaves no per-object `blocking` flag behind the way an
already-blocking creature does (`legal_actions_mixin`'s existing
`combat.blocking_attacker_ids(obj)` exclusion). Without a per-combat marker,
a defending player (or a client/bot polling on their behalf) kept seeing the
same "declare blocks" offer forever after answering "no blocks" — the
defending-side twin of the vigilant-attacker re-offer bug fixed the same day
(`test_vigilant_attacker_not_redeclared.py`).

Fix: `GameState.declared_blockers_this_combat` (a per-player id set), stamped
by `CombatMixin.declare_blockers` regardless of whether `assignments` was
empty, and checked by `legal_actions_mixin` before offering `declare_blockers`
again. Reset alongside every other per-combat flag in `_clear_combat()` (both
at `begin_turn`, before the first combat, and at `_step_end_combat`, before
any extra combat phase), so it never leaks into a later combat.

Reference: `models/game_state.py` (`declared_blockers_this_combat`),
`game/engine/combat_mixin.py` (`_clear_combat`, `declare_blockers`),
`game/engine/legal_actions_mixin.py`.
"""

from __future__ import annotations

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _creature(name, controller, power=2, toughness=2):
    card = Card(
        id=name, name=name, type_line="Creature — Bear",
        is_creature=True, power=power, toughness=toughness,
    )
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    return obj


def _attacker_and_blocker(eng, p1, p2):
    attacker = _creature("Attacker", p1.id)
    eng.state.add_to_battlefield(attacker)
    blocker = _creature("Blocker", p2.id)
    eng.state.add_to_battlefield(blocker)
    return attacker, blocker


def test_declaring_no_blocks_is_not_reoffered():
    eng = _engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    p2 = next(p for p in eng.state.players if p is not p1)
    attacker, blocker = _attacker_and_blocker(eng, p1, p2)

    eng.state.current_step = "declare_attackers"
    eng.declare_attackers(p1, [attacker])

    eng.state.current_step = "declare_blockers"
    assert any(a["type"] == "declare_blockers" for a in eng.legal_actions(p2))

    eng.declare_blockers(p2, [])  # RULE 509.1a: "declares no blocks"

    assert p2.id in eng.state.declared_blockers_this_combat
    assert not any(a["type"] == "declare_blockers" for a in eng.legal_actions(p2))
    # Unrelated to the attacking player's own offers.
    assert not any(a["type"] == "declare_blockers" for a in eng.legal_actions(p1))


def test_declaring_actual_blocks_also_marks_the_combat():
    eng = _engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    p2 = next(p for p in eng.state.players if p is not p1)
    attacker, blocker = _attacker_and_blocker(eng, p1, p2)

    eng.state.current_step = "declare_attackers"
    eng.declare_attackers(p1, [attacker])
    eng.state.current_step = "declare_blockers"
    eng.declare_blockers(p2, [{"blocker": blocker, "attacker": attacker}])

    assert p2.id in eng.state.declared_blockers_this_combat
    # Already covered by the per-object `blocking_attacker_ids` exclusion
    # (blocker is now busy) — the new marker must agree, not contradict it.
    assert not any(a["type"] == "declare_blockers" for a in eng.legal_actions(p2))


def test_marker_is_cleared_at_end_of_combat_and_does_not_leak():
    eng = _engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    p2 = next(p for p in eng.state.players if p is not p1)
    attacker, blocker = _attacker_and_blocker(eng, p1, p2)

    eng.state.current_step = "declare_attackers"
    eng.declare_attackers(p1, [attacker])
    eng.state.current_step = "declare_blockers"
    eng.declare_blockers(p2, [])
    assert p2.id in eng.state.declared_blockers_this_combat

    # RULE 511.3: combat ends — every per-combat marker resets, this one
    # included (mirrors `obj.attacking`/`blocked_by` cleared the same call).
    eng._step_end_combat()
    assert eng.state.declared_blockers_this_combat == set()

    # A fresh combat: the same attacker (tapped from the first swing) is
    # reset by hand here purely to re-arm the scenario, and the defender
    # must be offered "declare blocks" again rather than staying suppressed
    # from the previous combat.
    attacker.attacking = False
    attacker.tapped = False
    eng.state.current_step = "declare_attackers"
    eng.declare_attackers(p1, [attacker])
    eng.state.current_step = "declare_blockers"
    assert any(a["type"] == "declare_blockers" for a in eng.legal_actions(p2))


def test_begin_turn_also_clears_a_stale_marker():
    # Belt-and-suspenders: `begin_turn` calls `_clear_combat()` too (before
    # the turn's own first combat), so a marker somehow left over from a
    # prior state must not survive it either.
    eng = _engine()
    eng.begin_turn()
    p2 = next(p for p in eng.state.players if p is not eng.state.active_player)
    eng.state.declared_blockers_this_combat.add(p2.id)

    eng._clear_combat()
    assert eng.state.declared_blockers_this_combat == set()

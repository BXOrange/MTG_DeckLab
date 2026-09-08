"""Tests for `TaxedDrawEffect` (MEC-12's cEDH-decks batch, first pass) —
RULE 118.3's "unless" idiom applied to a draw rather than a
sacrifice/counter: Rhystic Study, Mystic Remora, Esper Sentinel.

These three were hand-authored (`game/ability_catalogue.py`) but had never
gained a committed pytest file — only an ad hoc scratchpad script during the
batch that first shipped them. Written against the real cached cards (the
same `tests/test_cube_batch_a1.py` house style) so a `TaxedDrawEffect`
regression or an oracle-text drift on any of the three shows up here.

Reference: mtg_analyzer/game/{effects,ability_catalogue}.py, RULE 118.3.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

pytestmark = pytest.mark.skipif(
    not DEFAULT_DB_PATH.exists(), reason="card cache not present in this environment"
)


def _card(name: str):
    db = CardDatabase(DEFAULT_DB_PATH)
    card = db.get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not present in the local card cache")
    return card


def two_player_engine():
    filler = _card("Lightning Bolt")
    eng = GameEngine.new_game(
        [("p1", "Alice", [filler] * 5), ("p2", "Bob", [filler] * 5)],
        starting_hand=0,
    )
    return eng, eng.state.player_by_id("p1"), eng.state.player_by_id("p2")


def battlefield(eng, name, controller="p1"):
    obj = GameObject(_card(name), owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def to_hand(eng, name, controller="p1"):
    obj = GameObject(_card(name), owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    eng.state.player_by_id(controller).hand.append(obj)
    return obj


def advance_to_main(eng):
    while eng.state.current_phase != "precombat_main":
        eng.advance_step()
    eng.recompute_continuous_effects()


# ---------------------------------------------------------------------------
# Rhystic Study — plain {1} tax, any spell type
# ---------------------------------------------------------------------------


def test_rhystic_study_draws_when_the_opponent_declines():
    eng, p1, p2 = two_player_engine()
    battlefield(eng, "Rhystic Study", "p1")
    bolt = to_hand(eng, "Lightning Bolt", "p2")
    advance_to_main(eng)
    p2.mana_pool.add("R", 1)
    p2.mana_pool.add("C", 1)  # enough to pay the {1} tax, so declining is a real choice
    before = len(p1.hand)
    eng.cast_spell(p2, bolt, targets=[p1])
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "pay_cost_then"
    assert choice["player_id"] == "p2"  # the *caster* decides, not Rhystic Study's controller
    eng.resolve_pending_choice("decline")
    assert eng.state.pending_choice is None
    assert len(p1.hand) == before + 1


def test_rhystic_study_no_draw_when_the_opponent_pays():
    eng, p1, p2 = two_player_engine()
    battlefield(eng, "Rhystic Study", "p1")
    bolt = to_hand(eng, "Lightning Bolt", "p2")
    advance_to_main(eng)
    p2.mana_pool.add("R", 1)
    p2.mana_pool.add("C", 1)  # the {1} tax
    before = len(p1.hand)
    eng.cast_spell(p2, bolt, targets=[p1])
    eng.resolve_until_stable()
    eng.resolve_pending_choice("pay")
    assert eng.state.pending_choice is None
    assert len(p1.hand) == before
    assert p2.mana_pool.total() == 0


def test_rhystic_study_does_not_trigger_off_its_own_controllers_spell():
    eng, p1, p2 = two_player_engine()
    battlefield(eng, "Rhystic Study", "p1")
    bolt = to_hand(eng, "Lightning Bolt", "p1")
    advance_to_main(eng)
    p1.mana_pool.add("R", 1)
    eng.cast_spell(p1, bolt, targets=[p2])
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None
    assert eng.state.stack == []


def test_rhystic_study_auto_draws_when_the_opponent_cannot_pay():
    # No pending_choice opens — the "goldfish dummy has no mana" case, same
    # idiom `counter_unless_pays`/`request_pay_cost_then` already use.
    eng, p1, p2 = two_player_engine()
    battlefield(eng, "Rhystic Study", "p1")
    bolt = to_hand(eng, "Lightning Bolt", "p2")
    advance_to_main(eng)
    p2.mana_pool.add("R", 1)  # exactly enough for the Bolt, nothing left for {1}
    before = len(p1.hand)
    eng.cast_spell(p2, bolt, targets=[p1])
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None
    assert len(p1.hand) == before + 1


# ---------------------------------------------------------------------------
# Mystic Remora — {4} tax, noncreature spells only
# ---------------------------------------------------------------------------


def test_mystic_remora_taxes_a_noncreature_spell():
    eng, p1, p2 = two_player_engine()
    bolt = to_hand(eng, "Lightning Bolt", "p2")
    # MEC-16: Mystic Remora's own Cumulative Upkeep {1} (previously a
    # documented simplification, "dropped — Mystic Remora simply never has
    # to be paid for") is now real behaviour, bound independently of this
    # card's hand-authored `taxed_draw` trigger — landing it on the
    # battlefield *after* advancing past p1's own upkeep (rather than
    # funding that upkeep, which RULE 500.4 empties the mana pool before
    # anyway) keeps this test about the tax, not the upkeep cost.
    advance_to_main(eng)
    remora = battlefield(eng, "Mystic Remora", "p1")
    assert remora in eng.state.battlefield
    p2.mana_pool.add("R", 1)
    p2.mana_pool.add("C", 4)  # enough to pay the {4} tax — a real choice, not an auto-draw
    eng.cast_spell(p2, bolt, targets=[p1])
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "pay_cost_then"


def test_mystic_remora_ignores_a_creature_spell():
    # Mystic Remora's controller is p2 here and the caster is p1 (the
    # active player in a fresh `new_game`) rather than the other way
    # around, purely so the creature spell is legal to cast at all (RULE
    # 307.4a sorcery-speed: only the active player may cast one) — p1 is
    # still Remora's "opponent" from p2's perspective either way.
    eng, p1, p2 = two_player_engine()
    battlefield(eng, "Mystic Remora", "p2")
    bear = to_hand(eng, "Grizzly Bears", "p1")
    advance_to_main(eng)
    p1.mana_pool.add("G", 1)
    p1.mana_pool.add("C", 1)
    eng.cast_spell(p1, bear)
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None
    assert eng.state.stack == []  # the creature spell resolved uninterrupted


# ---------------------------------------------------------------------------
# Esper Sentinel — {X} tax where X is its own live power, noncreature only
# ---------------------------------------------------------------------------


def test_esper_sentinel_tax_scales_with_its_own_power():
    eng, p1, p2 = two_player_engine()
    sentinel = battlefield(eng, "Esper Sentinel", "p1")
    assert sentinel.power == 1
    bolt = to_hand(eng, "Lightning Bolt", "p2")
    advance_to_main(eng)
    p2.mana_pool.add("R", 1)
    p2.mana_pool.add("C", 1)  # enough to pay the {1} (=power) tax
    before = len(p1.hand)
    eng.cast_spell(p2, bolt, targets=[p1])
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "pay_cost_then"
    assert choice["prompt"].startswith("{1}")  # X = 1, its printed power
    eng.resolve_pending_choice("decline")
    assert len(p1.hand) == before + 1


def test_esper_sentinel_ignores_a_creature_spell():
    # Same caster/controller swap as `test_mystic_remora_ignores_a_creature_
    # spell` above, and for the same reason (RULE 307.4a sorcery speed).
    eng, p1, p2 = two_player_engine()
    battlefield(eng, "Esper Sentinel", "p2")
    bear = to_hand(eng, "Grizzly Bears", "p1")
    advance_to_main(eng)
    p1.mana_pool.add("G", 1)
    p1.mana_pool.add("C", 1)
    eng.cast_spell(p1, bear)
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None

"""Tests for MEC-18 — RULE 603.5's general "You may `<cost-shaped action>`.
When/If you do, `<effect>`." optional-antecedent family.

No new engine primitive: `PayCostThenEffect`/`RulesEngine.
request_pay_cost_then` (RULE 118.3) already generalized mana/sacrifice/
discard/life payment behind one interactive "can you afford it, do you want
to, then pay it" gate (Rhystic Study/Mana Vault/Wandering Archaic). The gap
closed here is a parser one: `catalogue.handlers._pay_cost_then_general`
widens oracle-text recognition from the two hardcoded shapes that already
existed (a bare mana cost + "draw a card"; `{E}` pips + an arbitrary
follow-up) to the whole cost vocabulary, and `segmenter.
_PAY_ENERGY_THEN_PEEL_GUARD_RE` had to widen alongside it — the generic
"you may " stripper (`_peel_optional`) would otherwise eat the "you may"
this family's own interactive gate needs before `pay_cost_then_general`
ever sees the clause.

Reference: mtg_analyzer/parser/oracle/catalogue/handlers.py
(`_pay_cost_then_general`, `_MAY_COST_THEN_CLAUSE`), mtg_analyzer/parser/
oracle/segmenter.py (`_PAY_ENERGY_THEN_PEEL_GUARD_RE`), RULE 118.3/603.5.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
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
# Parse-level: coverage + no double-optional / no over-matching regression
# ---------------------------------------------------------------------------


def test_academy_raider_is_fully_modeled():
    result = parse_oracle(_card("Academy Raider"))
    assert result.coverage == "MODELED"
    triggered = [s for s in result.specs if s.ability_kind == "triggered"]
    assert len(triggered) == 1
    types = [e.type for e in triggered[0].effects]
    assert types == ["pay_cost_then"]
    assert triggered[0].effects[0].params["cost"] == "discard a card"


def test_abandon_attachments_is_fully_modeled_as_a_spell_effect():
    result = parse_oracle(_card("Abandon Attachments"))
    assert result.coverage == "MODELED"
    spell_effects = [s for s in result.specs if s.ability_kind == "spell_effect"]
    assert len(spell_effects) == 1
    assert spell_effects[0].effects[0].type == "pay_cost_then"


def test_dokuchi_silencer_targeted_followup_stays_unclaimed():
    """"You may discard a card. When you do, destroy target creature or
    planeswalker" — `pay_cost_then`'s branch effects resolve off-stack with
    no target-gathering step, so a targeted follow-up must stay a fail-closed
    gap rather than be half-modeled (docs/09). Guards against silently
    widening `_pay_cost_then_general` to accept targets without also
    teaching `PayCostThenEffect` to gather them.
    """
    result = parse_oracle(_card("A-Dokuchi Silencer"))
    assert result.coverage == "UNMODELED"


def test_self_sacrifice_when_you_do_still_uses_the_plain_sequence_path():
    """The Falcon, Airship Restored — "you may sacrifice it. When you do,
    return target creature card…" — must keep resolving through the older
    `_SACRIFICE_THEN_WHEN_YOU_DO_RE` collapse (an unconditional sequence,
    self-sacrifice is always legal once declared), NOT through
    `pay_cost_then_general`: that path forbids a targeted follow-up, and
    self-sacrifice's own outer "you may" peel already handles the real
    RULE 603.5 optionality correctly. `_MAY_COST_THEN_CLAUSE` deliberately
    excludes bare self-sacrifice forms to keep this working — see its
    docstring.
    """
    result = parse_oracle(_card("The Falcon, Airship Restored"))
    assert result.coverage == "MODELED"
    triggered = [s for s in result.specs if s.ability_kind == "triggered"]
    assert triggered, "expected the combat-damage trigger to be modeled"
    types = [e.type for e in triggered[0].effects]
    assert "sacrifice_self" in types
    assert "pay_cost_then" not in types


def test_pay_energy_then_still_recognized_after_the_guard_widened():
    result = parse_oracle(_card("Aether Chaser"))
    assert result.coverage == "MODELED"
    triggered = [s for s in result.specs if s.ability_kind == "triggered"]
    types = {e.type for spec in triggered for e in spec.effects}
    assert "pay_energy_then" in types


# ---------------------------------------------------------------------------
# Execute: Abandon Attachments (spell-level "you may discard. when you do,
# draw two")
# ---------------------------------------------------------------------------


def test_abandon_attachments_draws_two_when_discarding():
    eng, p1, _p2 = two_player_engine()
    spell = to_hand(eng, "Abandon Attachments", "p1")
    filler = to_hand(eng, "Lightning Bolt", "p1")  # the card that gets discarded
    advance_to_main(eng)
    p1.mana_pool.add("U", 1)
    p1.mana_pool.add("C", 1)
    before = len(p1.hand)
    eng.cast_spell(p1, spell, targets=[])
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "pay_cost_then"
    assert choice["player_id"] == "p1"
    eng.resolve_pending_choice("pay")
    assert eng.state.pending_choice is None
    # -1 (spell cast) -1 (discarded) +2 (drawn) relative to the pre-cast hand
    assert len(p1.hand) == before - 1 - 1 + 2
    assert filler not in p1.hand


def test_abandon_attachments_no_draw_when_declining():
    eng, p1, _p2 = two_player_engine()
    spell = to_hand(eng, "Abandon Attachments", "p1")
    to_hand(eng, "Lightning Bolt", "p1")
    advance_to_main(eng)
    p1.mana_pool.add("U", 1)
    p1.mana_pool.add("C", 1)
    before = len(p1.hand)
    eng.cast_spell(p1, spell, targets=[])
    eng.resolve_until_stable()
    eng.resolve_pending_choice("decline")
    assert eng.state.pending_choice is None
    assert len(p1.hand) == before - 1  # only the spell itself left the hand


def test_abandon_attachments_never_offered_with_an_empty_hand():
    """`_can_pay_player_cost` must gate the offer itself — a discard cost
    genuinely can fail, unlike the self-sacrifice family this handler
    deliberately stays out of (see the parse-level test above)."""
    eng, p1, _p2 = two_player_engine()
    spell = to_hand(eng, "Abandon Attachments", "p1")
    advance_to_main(eng)
    p1.mana_pool.add("U", 1)
    p1.mana_pool.add("C", 1)
    before = len(p1.hand)
    eng.cast_spell(p1, spell, targets=[])
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None  # nothing to discard, auto-declined
    assert len(p1.hand) == before - 1


# ---------------------------------------------------------------------------
# Execute: Academy Raider (triggered "you may discard. when you do, draw")
# ---------------------------------------------------------------------------


def test_academy_raider_offers_discard_on_combat_damage_and_draws():
    eng, p1, p2 = two_player_engine()
    raider = battlefield(eng, "Academy Raider", "p1")
    to_hand(eng, "Lightning Bolt", "p1")
    advance_to_main(eng)
    before = len(p1.hand)
    eng.rules.deal_damage(p2, 1, source=raider, combat=True)
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "pay_cost_then"
    eng.resolve_pending_choice("pay")
    assert eng.state.pending_choice is None
    assert len(p1.hand) == before  # -1 discarded, +1 drawn


def test_academy_raider_no_pending_choice_with_empty_hand():
    eng, p1, p2 = two_player_engine()
    raider = battlefield(eng, "Academy Raider", "p1")
    advance_to_main(eng)
    before = len(p1.hand)
    eng.rules.deal_damage(p2, 1, source=raider, combat=True)
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None
    assert len(p1.hand) == before

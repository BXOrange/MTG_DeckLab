"""Tests for PAR-7: Kicker's own {X} (RULE 702.33b) — Emblazoned Golem's
"Kicker {X}" / "Spend only colored mana on X. No more than one mana of each
color may be spent this way." / "If this creature was kicked, it enters with
X +1/+1 counters on it." Three cooperating pieces:

- `models.mana.mana_pool.ManaPool.can_pay_distinct_colors`/`pay_distinct_colors`/
  `clone` — the RULE 605.3a-style "no more than one mana of each color"
  payment primitive.
- `GameEngine.can_cast`/`effective_cast_cost`/`cast_spell`'s new `kicker_x`
  parameter, and `max_affordable_kicker_x`/`legal_actions`' `kicker_has_x`/
  `kicker_max_x` offer fields.
- `parser/oracle/catalogue/counters.py`'s widened kicked-gate regex
  (`kicked_x_scale`) and the new `parser/oracle/catalogue/kicker_mana.py`
  recognizer, both wired into `gate.py` the same "claim without a spec"
  way `entry_counters`/tapped-entry already are.
"""

from mtg_analyzer.game.ability_catalogue import kicker_x_mana_restriction
from mtg_analyzer.game.binding.core import attach_to_object
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.models.mana.mana_pool import ManaPool
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.counters import entry_counters_condition
from mtg_analyzer.parser.oracle.catalogue.kicker_mana import (
    KICKER_X_DISTINCT_COLORS,
    kicker_x_mana_restriction_condition,
)


_GOLEM_TEXT = (
    "Kicker {X} (You may pay an additional {X} as you cast this spell.)\n"
    "Spend only colored mana on X. No more than one mana of each color may be spent this way.\n"
    "If this creature was kicked, it enters with X +1/+1 counters on it."
)


def _golem_card(name="Emblazoned Golem"):
    card = Card(
        id=name, name=name, type_line="Artifact Creature — Golem",
        mana_cost_string="{2}", converted_mana_cost=2,
        is_creature=True, power=1, toughness=2,
        oracle_text=_GOLEM_TEXT,
    )
    card.keywords = ["Kicker"]
    return card


def _make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )


def _golem_in_hand(eng, p1):
    card = _golem_card()
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, result.specs)
    p1.hand.append(obj)
    return obj


# ---------------------------------------------------------------------------
# PARSER: the "spend only colored mana on X" restriction clause
# ---------------------------------------------------------------------------


def test_kicker_x_distinct_color_restriction_is_recognized():
    line = "spend only colored mana on x. no more than 1 mana of each color may be spent this way."
    assert kicker_x_mana_restriction_condition(line) == KICKER_X_DISTINCT_COLORS


def test_kicker_x_distinct_color_restriction_rejects_a_near_miss():
    # Two colors, not one — a different (unmodeled) restriction shape.
    assert kicker_x_mana_restriction_condition(
        "spend only colored mana on x. no more than 2 mana of each color may be spent this way."
    ) is None


def test_kicker_x_mana_restriction_reads_off_the_real_card():
    assert kicker_x_mana_restriction(_golem_card()) == KICKER_X_DISTINCT_COLORS


def test_kicker_x_mana_restriction_is_none_for_a_plain_kicker_card():
    card = Card(
        id="Sengir Nemesis", name="Sengir Nemesis", type_line="Creature",
        mana_cost_string="{2}{B}", converted_mana_cost=3, is_creature=True,
        power=2, toughness=2, oracle_text="Kicker {1}{B} (You may pay an additional {1}{B} as you cast this spell.)",
    )
    assert kicker_x_mana_restriction(card) is None


# ---------------------------------------------------------------------------
# PARSER: the kicked-gate "enters with X counters" shape (kicked_x_scale)
# ---------------------------------------------------------------------------


def test_kicked_gate_entry_counters_accepts_x_as_the_amount():
    condition = entry_counters_condition("if ~ was kicked, it enters with x +1/+1 counters on it.")
    assert condition == {"is_x": False, "counter_type": "+1/+1", "kicked_gate": True, "kicked_x_scale": True}


def test_kicked_gate_entry_counters_still_accepts_a_fixed_amount():
    # Regression: widening the amount group to allow "x" must not break the
    # existing fixed-count shape (Academy Drake-shaped).
    condition = entry_counters_condition("if ~ was kicked, it enters with 2 +1/+1 counters on it.")
    assert condition == {"is_x": False, "count": 2, "counter_type": "+1/+1", "kicked_gate": True}


def test_kicked_scaled_entry_counters_does_not_accept_x():
    # The Multikicker-scaled ("...for each time it was kicked") shape stays
    # fixed-amount-only — no cache card scales a per-kick amount by an
    # independently announced Kicker {X}.
    assert entry_counters_condition(
        "~ enters with x +1/+1 counters on it for each time it was kicked."
    ) is None


# ---------------------------------------------------------------------------
# END TO END: Emblazoned Golem is fully MODELED
# ---------------------------------------------------------------------------


def test_emblazoned_golem_is_fully_modeled():
    result = parse_oracle(_golem_card())
    assert result.modeled
    assert result.unclaimed == []


# ---------------------------------------------------------------------------
# models/mana_pool.py: the distinct-colors payment primitive
# ---------------------------------------------------------------------------


def test_can_pay_distinct_colors_counts_colors_not_total_mana():
    pool = ManaPool({"R": 3})  # three mana, but only one distinct color
    assert pool.can_pay_distinct_colors(1) is True
    assert pool.can_pay_distinct_colors(2) is False


def test_can_pay_distinct_colors_ignores_colorless_and_generic():
    pool = ManaPool({"C": 5})
    assert pool.can_pay_distinct_colors(1) is False


def test_can_pay_distinct_colors_zero_is_always_payable():
    assert ManaPool().can_pay_distinct_colors(0) is True


def test_pay_distinct_colors_spends_one_of_each_color():
    starting = {"W": 1, "U": 1, "B": 2}
    pool = ManaPool(starting)
    pool.pay_distinct_colors(2)
    spent = {c: starting[c] - pool.pool[c] for c in starting}
    # Exactly two mana total spent, never more than one from any color.
    assert sum(spent.values()) == 2
    assert all(v in (0, 1) for v in spent.values())


def test_pay_distinct_colors_raises_when_unpayable():
    pool = ManaPool({"R": 1})
    try:
        pool.pay_distinct_colors(2)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_clone_is_independent_of_the_original():
    pool = ManaPool({"W": 2})
    clone = pool.clone()
    clone.pool["W"] = 0
    assert pool.pool["W"] == 2


# ---------------------------------------------------------------------------
# ENGINE: can_cast / cast_spell / max_affordable_kicker_x
# ---------------------------------------------------------------------------


def test_can_cast_unkicked_needs_only_the_printed_cost():
    eng = _make_engine()
    p1 = eng.state.players[0]
    obj = _golem_in_hand(eng, p1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"C": 2})
    assert eng.can_cast(p1, obj) is True


def test_can_cast_kicked_with_kicker_x_needs_that_many_distinct_colors():
    eng = _make_engine()
    p1 = eng.state.players[0]
    obj = _golem_in_hand(eng, p1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    # {2} printed cost, plus Kicker X=2 needing 2 distinct colors.
    p1.mana_pool.add_many({"C": 2, "W": 1, "U": 1})
    assert eng.can_cast(p1, obj, kicked=1, kicker_x=2) is True


def test_can_cast_kicked_refuses_when_not_enough_distinct_colors():
    eng = _make_engine()
    p1 = eng.state.players[0]
    obj = _golem_in_hand(eng, p1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    # Only one distinct color (three R) — can't pay X=2 even though there's
    # "enough mana" by raw count.
    p1.mana_pool.add_many({"C": 2, "R": 3})
    assert eng.can_cast(p1, obj, kicked=1, kicker_x=2) is False


def test_can_cast_kicked_refuses_when_printed_cost_and_kicker_x_would_share_mana():
    eng = _make_engine()
    p1 = eng.state.players[0]
    obj = _golem_in_hand(eng, p1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    # Exactly 2 colored mana total: the printed {2} would have to eat into
    # it, leaving nothing for Kicker's own distinct-color X=2 — a naive
    # "check both independently against the same pool" implementation would
    # wrongly allow this.
    p1.mana_pool.add_many({"W": 1, "U": 1})
    assert eng.can_cast(p1, obj, kicked=1, kicker_x=2) is False


def test_max_affordable_kicker_x_scans_down_to_the_payable_value():
    eng = _make_engine()
    p1 = eng.state.players[0]
    obj = _golem_in_hand(eng, p1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"C": 2, "W": 1, "U": 1, "B": 1})
    assert eng.max_affordable_kicker_x(p1, obj) == 3


def test_max_affordable_kicker_x_is_zero_for_a_plain_kicker_card():
    eng = _make_engine()
    p1 = eng.state.players[0]
    card = Card(
        id="Sengir Nemesis", name="Sengir Nemesis", type_line="Creature",
        mana_cost_string="{2}{B}", converted_mana_cost=3, is_creature=True,
        power=2, toughness=2, oracle_text="Kicker {1}{B} (You may pay an additional {1}{B} as you cast this spell.)",
    )
    card.keywords = ["Kicker"]
    result = parse_oracle(card)
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, result.specs)
    p1.hand.append(obj)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"C": 10, "B": 10})
    assert eng.max_affordable_kicker_x(p1, obj) == 0


def test_legal_actions_offer_kicker_has_x_and_kicker_max_x():
    eng = _make_engine()
    p1 = eng.state.players[0]
    obj = _golem_in_hand(eng, p1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"C": 2, "W": 1, "U": 1})
    actions = eng.legal_actions(p1)
    cast = next(a for a in actions if a["type"] == "cast_spell" and a["instance_id"] == obj.instance_id)
    assert cast["has_kicker"] is True
    assert cast["kicker_has_x"] is True
    assert cast["kicker_max_x"] == 2


# ---------------------------------------------------------------------------
# ENGINE: end-to-end cast, mana payment, and the entry-counters payoff
# ---------------------------------------------------------------------------


def test_unkicked_golem_enters_with_no_counters():
    eng = _make_engine()
    p1 = eng.state.players[0]
    obj = _golem_in_hand(eng, p1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"C": 2})
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()
    battlefield_obj = next(o for o in eng.state.battlefield if o.name == "Emblazoned Golem")
    assert battlefield_obj.counters.get("+1/+1", 0) == 0
    assert battlefield_obj.power == 1 and battlefield_obj.toughness == 2


def test_kicked_golem_enters_with_x_counters_and_pays_correctly():
    eng = _make_engine()
    p1 = eng.state.players[0]
    obj = _golem_in_hand(eng, p1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"C": 2, "W": 1, "U": 1})
    eng.cast_spell(p1, obj, kicked=1, kicker_x=2)
    eng.resolve_until_stable()

    battlefield_obj = next(o for o in eng.state.battlefield if o.name == "Emblazoned Golem")
    assert battlefield_obj.counters.get("+1/+1", 0) == 2
    assert battlefield_obj.power == 3 and battlefield_obj.toughness == 4
    assert battlefield_obj.kicker_count == 1
    assert battlefield_obj.kicker_x_paid == 2
    # Every mana in the pool was spent: {2} generic (colorless) + 2 distinct
    # colors for Kicker's own X.
    assert p1.mana_pool.pool["C"] == 0
    assert p1.mana_pool.pool["W"] == 0
    assert p1.mana_pool.pool["U"] == 0


def test_kicked_golem_with_x_zero_enters_with_no_counters():
    # RULE 601.2b: kicking with an announced X of 0 is legal (you paid
    # Kicker, you just announced nothing for its own {X}) but shouldn't
    # scale the counters.
    eng = _make_engine()
    p1 = eng.state.players[0]
    obj = _golem_in_hand(eng, p1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"C": 2})
    eng.cast_spell(p1, obj, kicked=1, kicker_x=0)
    eng.resolve_until_stable()
    battlefield_obj = next(o for o in eng.state.battlefield if o.name == "Emblazoned Golem")
    assert battlefield_obj.counters.get("+1/+1", 0) == 0
    assert battlefield_obj.kicker_count == 1

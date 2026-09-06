"""PAR-30 — Earthbend residue (card 1 of 3): "Earthbend N. When you do, <effect>."

RULE 701.66 + RULE 603.3's "when you do" sub-trigger. "earthbend N" is a
mandatory keyword action (no "may"), so RULE 603.3's reflexive trigger is a
certainty — the two sentences collapse to one plain `[earthbend N, <effect>]`
sequence with no interactive branch, the same certain-antecedent rationale
`_SACRIFICE_THEN_WHEN_YOU_DO_RE` uses. `_EARTHBEND_THEN_WHEN_YOU_DO_RE` in
`segmenter`. Closes Earth Rumble.

Still open in the Earthbend residue cluster (fail-closed here): Beifong's
Bounty Hunters ("earthbend X, where X is that creature's power" — a dying
creature's last-known power) and Earthshape ("earthbend N. then each creature
you control with power <= that land's power gains …").
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import build_effects
from mtg_analyzer.game.effects import _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _forest(state, pid="p1"):
    o = GameObject(
        Card(id="F", name="Forest", type_line="Basic Land — Forest", is_land=True),
        owner_id=pid, zone=Zone.BATTLEFIELD,
    )
    o.controller_id = pid
    state.add_to_battlefield(o)
    return o


# --- parse --------------------------------------------------------------


def test_earthbend_when_you_do_collapses_to_plain_sequence():
    specs = parse_effect_body(
        "earthbend 2. when you do, up to 1 target creature you control fights "
        "target creature an opponent controls."
    )
    assert specs is not None
    kinds = [s.type for s in specs]
    assert kinds == ["earthbend", "fight"]
    assert specs[0].params.get("amount") == 2


def test_optional_antecedent_does_not_collapse_here():
    # "you may earthbend 2. when you do, …" is the genuine RULE 603.3 optional
    # shape — this narrow collapse must not claim it (fails closed).
    assert parse_effect_body(
        "you may earthbend 2. when you do, draw a card."
    ) is None


def test_when_you_do_after_a_non_earthbend_clause_not_claimed():
    assert parse_effect_body("scry 2. when you do, draw a card.") is None


def test_real_card_earth_rumble_modeled():
    c = Card(
        id="ERUMBL", name="Earth Rumble", type_line="Sorcery", is_sorcery=True,
        oracle_text=(
            "Earthbend 2. When you do, up to one target creature you control "
            "fights target creature an opponent controls."
        ),
    )
    res = parse_oracle(c)
    assert res.coverage != UNMODELED, res.unclaimed


# --- execute ----------------------------------------------------------


def test_sequence_first_resolves_the_earthbend_half():
    eng, state = _engine()
    land = _forest(state)

    specs = parse_effect_body(
        "earthbend 5. when you do, up to 1 target creature you control fights "
        "target creature an opponent controls."
    )
    assert specs is not None and specs[0].type == "earthbend"

    effect = build_effects([specs[0]], land)[0]
    _apply_effects_partitioned([effect], eng.rules.context, [land], None, source=land)
    eng.recompute_continuous_effects()

    assert land.is_creature and land.is_land
    assert land.counters.get("+1/+1") == 5

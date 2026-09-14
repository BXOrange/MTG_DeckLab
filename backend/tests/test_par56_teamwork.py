"""PAR-56 — Teamwork (RULE 702.194) rider grammar beyond the modal
"choose both instead" shape.

The v377 batch had already wired the modal override (`modal.py`) and the
leading-additive "if this spell was cast using teamwork, `<extra effect>`"
prefix row (`segmenter._TEAMWORK_PAID_CONDITION_RE`), both emitting
``{"kind": "flag", "flag": "teamwork_paid"}`` — but **`"teamwork_paid"` was
never added to `static_conditions.SUBJECT_FLAGS`**, so `condition_holds`'s
"flag" branch (``name not in SUBJECT_FLAGS`` → fail closed) silently
evaluated it to ``False`` forever. The row *parsed* fine (a card carrying it
already counted as `MODELED`) but its rider would never actually fire in a
real game — exactly the "parses but is rules-wrong" trap `engine_bench.py`
exists to catch, caught here only by an execute-level test since the
coverage gate itself can't see it. This batch:

* Adds ``"teamwork_paid"`` to `SUBJECT_FLAGS` (+ its `_FROM_LEGACY`/
  `_ALLOWED_CONDITION_KEYS` mirrors, completing the same trio every other
  cast-time flag in that whitelist already has) — fixing the dormant bug.
* Adds "this spell"/"it was cast using teamwork" to `static_handlers.
  static_condition`'s shared vocabulary, so the **generic** trailing
  "`<effect>`, if/unless `<cond>`" gates (`segmenter._GENERIC_IF_SUFFIX_RE`/
  `_GENERIC_UNLESS_SUFFIX_RE`) recognize it too — a *different* grammatical
  shape than the existing leading-prefix row, closing Timeline Inquiry's
  "discard a card **unless** this spell was cast using teamwork."

Reference: mtg_analyzer/parser/oracle/segmenter.py,
mtg_analyzer/parser/oracle/catalogue/static_handlers.py,
mtg_analyzer/game/static_conditions.py.
"""

from __future__ import annotations

from mtg_analyzer.game import static_conditions
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effect_conditions import condition_from_legacy
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_condition
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def _engine(*player_ids):
    players = [Player(id=pid, life=20) for pid in player_ids]
    state = GameState(players=players)
    return GameEngine(state), state


# ---------------------------------------------------------------------------
# The dormant-bug fix: teamwork_paid actually evaluates now
# ---------------------------------------------------------------------------


def test_teamwork_paid_flag_is_whitelisted():
    assert "teamwork_paid" in static_conditions.SUBJECT_FLAGS


def test_condition_holds_reads_teamwork_paid_off_the_source():
    engine, state = _engine("p1")
    spell = GameObject(Card(id="s", name="s", type_line="Sorcery"), owner_id="p1", zone=Zone.STACK)
    spell.teamwork_paid = False
    assert static_conditions.condition_holds(
        {"kind": "flag", "flag": "teamwork_paid"}, state, spell, controller_id="p1",
    ) is False
    spell.teamwork_paid = True
    assert static_conditions.condition_holds(
        {"kind": "flag", "flag": "teamwork_paid"}, state, spell, controller_id="p1",
    ) is True


def test_legacy_flat_key_still_translates():
    assert condition_from_legacy({"teamwork_paid": True}) == {"kind": "flag", "flag": "teamwork_paid"}


# ---------------------------------------------------------------------------
# Leading-additive shape (already wired pre-batch, just now actually live)
# ---------------------------------------------------------------------------


def test_leading_if_cast_using_teamwork_parses_and_gates():
    specs = parse_effect_body("if this spell was cast using teamwork, draw a card")
    assert specs is not None and len(specs) == 1
    assert specs[0].condition == {"kind": "flag", "flag": "teamwork_paid"}


# ---------------------------------------------------------------------------
# Generic trailing "if"/"unless" gate — the new addition
# ---------------------------------------------------------------------------


def test_static_condition_recognizes_cast_using_teamwork_phrase():
    assert static_condition("this spell was cast using teamwork") == {
        "kind": "flag", "flag": "teamwork_paid",
    }
    assert static_condition("it was cast using teamwork") == {
        "kind": "flag", "flag": "teamwork_paid",
    }


def test_trailing_unless_cast_using_teamwork_parses_and_gates():
    specs = parse_effect_body("discard a card unless this spell was cast using teamwork")
    assert specs is not None and len(specs) == 1
    assert specs[0].condition == {
        "kind": "not", "condition": {"kind": "flag", "flag": "teamwork_paid"},
    }


def test_timeline_inquiry_is_modeled():
    r = parse_oracle(_db().get_card("Timeline Inquiry"))
    assert r.coverage != UNMODELED, r.unclaimed


def test_timeline_inquiry_is_bound_with_a_gated_discard():
    # The end-to-end proof that the whole chain (parser → EffectSpec.condition
    # → binding/core.py's `ConditionalEffect` wrap → SUBJECT_FLAGS) actually
    # connects, without wrestling with `DiscardEffect`'s own interactive
    # choice machinery (an unrelated, already-tested subsystem): confirm the
    # bound discard effect really is wrapped in a `ConditionalEffect` gated on
    # the negated flag, and that gate itself answers correctly either way.
    from mtg_analyzer.game.effects.game_status import ConditionalEffect

    spell = GameObject(_db().get_card("Timeline Inquiry"), owner_id="p1", controller_id="p1", zone=Zone.STACK)
    bind_from_catalogue(spell)
    gated = [e for e in spell.spell_effects if isinstance(e, ConditionalEffect)]
    assert len(gated) == 1
    assert gated[0].condition == {"kind": "not", "condition": {"kind": "flag", "flag": "teamwork_paid"}}

    engine, state = _engine("p1")
    context = engine.rules.context
    spell.teamwork_paid = True
    assert gated[0]._condition_holds(context) is False  # teamwork paid — no discard
    spell.teamwork_paid = False
    assert gated[0]._condition_holds(context) is True  # no teamwork — discard fires

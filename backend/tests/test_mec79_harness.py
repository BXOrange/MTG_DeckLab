"""MEC-79 — Harness (RULE 701.64).

`RulesEngine.harness(obj)` flips the RULE 701.64b **harnessed** designation
on a permanent (701.64a's "if this permanent isn't harnessed, it becomes
harnessed" — idempotent, fires `HARNESSED` only on the transition).
`effects.HarnessEffect` (registered `harness`) is the resolve-time body of
the Marvel Infinity Stones' ``{cost}, {T}: Harness ~`` ability.
`static_conditions`' ``source_harnessed`` is the read path — the Stones' ``∞``
ability is gated on it, which `normalize._rewrite_infinity_ability` wires up
by turning the ``∞ —`` marker line into an ordinary phase trigger carrying a
RULE 603.4 ``if ~ is harnessed`` intervening-if.

Reference: game/rules/misc_mixin.py (`harness`), game/effects/core.py
(`HarnessEffect`), game/static_conditions.py (`source_harnessed`),
parser/oracle/{normalize,segmenter}.py, parser/oracle/catalogue/handlers.py.
"""

from __future__ import annotations

from mtg_analyzer.game import isa
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import EffectRegistry, HarnessEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.static_conditions import condition_holds
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.normalize import normalize
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _artifact(state, name="Stone", controller="p1"):
    obj = GameObject(
        Card(id=name, name=name, type_line="Legendary Artifact — Infinity Stone"),
        owner_id=controller, zone=Zone.BATTLEFIELD,
    )
    state.add_to_battlefield(obj)
    return obj


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


# --- primitive -----------------------------------------------------------


def test_harness_flips_designation_once_and_fires_event():
    eng = _engine()
    stone = _artifact(eng.state)
    seen: list = []
    eng.state.subscribe(lambda e: seen.append(e) if e.type == EventType.HARNESSED else None)

    assert stone.harnessed is False
    assert eng.rules.harness(stone) is True
    assert stone.harnessed is True
    assert len(seen) == 1
    assert seen[0].get("instance_id") == stone.instance_id

    # 701.64a: a second harness is a no-op, event included.
    assert eng.rules.harness(stone) is False
    assert len(seen) == 1


def test_harness_effect_targets_source():
    eng = _engine()
    stone = _artifact(eng.state)
    HarnessEffect(source=stone).apply(eng.rules.context)
    assert stone.harnessed is True


def test_harnessed_cleared_when_object_leaves_battlefield():
    # RULE 701.64b / 400.7 — harnessed stays only "until it leaves the
    # battlefield"; the returning object is new and not harnessed.
    eng = _engine()
    stone = _artifact(eng.state)
    eng.rules.harness(stone)
    stone.reset_as_new_object()
    assert stone.harnessed is False


# --- the source_harnessed condition ------------------------------------


def test_source_harnessed_condition_reads_the_flag():
    eng = _engine()
    stone = _artifact(eng.state)
    cond = {"kind": "source_harnessed"}
    assert condition_holds(cond, eng.state, source=stone, controller_id="p1") is False
    eng.rules.harness(stone)
    assert condition_holds(cond, eng.state, source=stone, controller_id="p1") is True


# --- parser ----------------------------------------------------------


def test_harness_clause_parses():
    assert match_clause("harness ~") == [EffectSpec("harness", {})]
    assert match_clause("harness this permanent") == [EffectSpec("harness", {})]
    # 701.64a defines no amount / no "target" form.
    assert match_clause("harness 2") is None


def test_normalize_rewrites_infinity_marker_line():
    text = (
        "{5}{W}, {T}: Harness The Mind Stone. (Once harnessed, its ∞ ability is active.)\n"
        "∞ — At the beginning of your end step, draw a card."
    )
    out = normalize(text, "The Mind Stone")
    assert "∞" not in out
    assert "at the beginning of your end step, if ~ is harnessed, draw a card" in out


def test_harness_effect_registered_and_classified():
    assert EffectRegistry.is_registered("harness")
    assert isa.EFFECT_TYPES["harness"].instruction == "harness"


def test_infinity_stones_fully_modeled_with_gated_trigger():
    for name in ("The Mind Stone", "The Soul Stone"):
        card = _db().get_card(name)
        assert card is not None, name
        result = parse_oracle(card)
        assert result.coverage != UNMODELED, name
        kinds = {s.ability_kind for s in result.specs}
        assert {"activated", "triggered"} <= kinds, name
        activated = next(s for s in result.specs if s.ability_kind == "activated")
        assert [e.type for e in activated.effects] == ["harness"]
        triggered = next(s for s in result.specs if s.ability_kind == "triggered")
        assert triggered.trigger.get("active_if") == {"kind": "source_harnessed"}


def test_the_mind_stone_binds_a_gated_end_step_trigger():
    eng = _engine()
    card = _db().get_card("The Mind Stone")
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    trigs = obj.triggered_abilities
    assert len(trigs) == 1
    # the ∞ blink only functions once harnessed (RULE 701.64b)
    assert obj.harnessed is False
    eng.rules.harness(obj)
    assert obj.harnessed is True


def test_blink_plain_handler_accepts_other_qualifier():
    # MEC-79 widened `_BLINK_PLAIN_RE` from "(another )?" to "((an)?other )?"
    # — the source-excluding *_you_control target kind makes them equivalent.
    specs = match_clause(
        "exile up to 1 other target nonland permanent you control, then return "
        "that card to the battlefield under its owner's control"
    )
    assert specs is not None
    assert specs[0].type == "blink"
    assert specs[0].params["target_kind"] == "nonland_permanent_you_control"

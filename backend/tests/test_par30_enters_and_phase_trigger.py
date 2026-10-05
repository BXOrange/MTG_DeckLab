"""PAR-30 (Threaten / O-Ring trailing items) — the compound "when ~ enters
and at the beginning of your first main phase" trigger (Crack in Time).

`segmenter._ENTERS_AND_MAIN_PHASE_RE` splits it into one self
`ENTERS_BATTLEFIELD` spec + one controller-scoped `STEP_BEGIN`
(`filter={"step": "main1"}`, `phase_relation="you"`), and — the body being
an "exile … until ~ leaves the battlefield" O-Ring clause — the companion
`LEAVES_BATTLEFIELD` → `return_linked_exile` spec.
"""

from __future__ import annotations

from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import ParserProvenance
from mtg_analyzer.models.cards.card import Card

_PROV = ParserProvenance(version="test", source="rule:oracle", confidence=1.0)


def test_segment_splits_into_enters_plus_phase_plus_ltb():
    seg = segment_line(
        "when ~ enters and at the beginning of your first main phase, exile "
        "target creature an opponent controls until ~ leaves the battlefield.",
        allow_spell_effect=False, provenance=_PROV,
    )
    assert seg.claimed
    events = [seg.spec.trigger["event"]] + [x.trigger["event"] for x in seg.extra_specs]
    assert set(events) == {"ENTERS_BATTLEFIELD", "STEP_BEGIN", "LEAVES_BATTLEFIELD"}
    phase = next(x for x in [seg.spec, *seg.extra_specs]
                 if x.trigger["event"] == "STEP_BEGIN")
    assert phase.trigger["filter"] == {"step": "main1"}
    assert phase.trigger["phase_relation"] == "you"


def test_segment_precombat_main_spelling():
    seg = segment_line(
        "when ~ enters and at the beginning of your precombat main phase, "
        "draw a card.",
        allow_spell_effect=False, provenance=_PROV,
    )
    assert seg.claimed
    assert {seg.spec.trigger["event"],
            seg.extra_specs[0].trigger["event"]} == {"ENTERS_BATTLEFIELD", "STEP_BEGIN"}


def test_real_crack_in_time_modeled():
    c = Card(
        id="CIT", name="Crack in Time", type_line="Enchantment", keywords=["Vanishing"],
        oracle_text=(
            "Vanishing 3 (This enchantment enters with three time counters on "
            "it. At the beginning of your upkeep, remove a time counter from "
            "it. When the last is removed, sacrifice it.)\n"
            "When Crack in Time enters and at the beginning of your first main "
            "phase, exile target creature an opponent controls until Crack in "
            "Time leaves the battlefield."
        ),
    )
    r = parse_oracle(c)
    assert r.modeled is True
    events = {e for s in r.specs if s.ability_kind == "triggered"
              for e in ([s.trigger["event"]] if isinstance(s.trigger["event"], str)
                        else s.trigger["event"])}
    assert {"ENTERS_BATTLEFIELD", "STEP_BEGIN", "LEAVES_BATTLEFIELD"} <= events

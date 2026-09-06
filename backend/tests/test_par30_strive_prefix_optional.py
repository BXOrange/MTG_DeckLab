"""PAR-30 — Strive (MEC-4) recognition when `normalize` has already
stripped the "Strive —" label.

`normalize._strip_unregistered_keyword_labels` removes "Strive —" (Scryfall
lists "Strive" in the card's `keywords` array but it is not a registered
RULE 701/702 keyword), so the sentence reaching the segmenter is just
"This spell costs {cost} more to cast for each target beyond the first."
`_STRIVE_LINE_RE`'s "Strive —" prefix is now optional. The engine
(`AbilitySpec.strive_cost` → `obj.strive_cost` → `effective_cast_cost`)
was already complete.
"""

from __future__ import annotations

from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.parser.oracle.spec import ParserProvenance
from mtg_analyzer.models.card import Card


def _seg(text):
    return segment_line(text, allow_spell_effect=True, provenance=ParserProvenance())


def test_bare_strive_line_parses():
    seg = _seg("this spell costs {2}{u} more to cast for each target beyond the first.")
    assert seg.claimed and seg.spec is not None
    assert seg.spec.strive_cost == "{2}{u}"


def test_labelled_strive_line_still_parses():
    seg = _seg("strive — this spell costs {r}{w} more to cast for each target beyond the first.")
    assert seg.claimed and seg.spec.strive_cost == "{r}{w}"


def test_single_symbol_cost():
    seg = _seg("this spell costs {r} more to cast for each target beyond the first.")
    assert seg.spec.strive_cost == "{r}"


def test_not_a_strive_line_is_unclaimed():
    seg = _seg("this spell costs {2} less to cast for each artifact you control.")
    assert not seg.claimed or seg.spec is None or seg.spec.strive_cost is None


def test_aerial_formation_modeled():
    c = Card(
        id="af", name="Aerial Formation", type_line="Instant", is_instant=True,
        keywords=["Strive"], oracle_text=(
            "Strive — This spell costs {2}{U} more to cast for each target "
            "beyond the first.\nAny number of target creatures each get +1/+1 "
            "and gain flying until end of turn."),
    )
    assert parse_oracle(c).coverage != UNMODELED, parse_oracle(c).unclaimed


def test_rouse_the_mob_modeled():
    c = Card(
        id="rtm", name="Rouse the Mob", type_line="Instant", is_instant=True,
        keywords=["Strive"], oracle_text=(
            "Strive — This spell costs {2}{R} more to cast for each target "
            "beyond the first.\nAny number of target creatures each get "
            "+2/+2 and gain trample until end of turn."),
    )
    assert parse_oracle(c).coverage != UNMODELED, parse_oracle(c).unclaimed

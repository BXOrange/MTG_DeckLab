"""PAR-69: "Doctor's companion" (RULE 702.124m, Doctor Who) — the third
partner-ability variant alongside Partner (702.124h) and Choose a
Background (702.124k), all part of the same RULE 702.124 keyword-ability
family: "keyword abilities that modify the rules for deck construction in
the Commander variant … and function before the game begins" (RULE
702.124a). Just as inert in-game as its siblings — pairing a
Doctor's-companion card with a legendary Time Lord Doctor creature is
`services/commander_legality.py`'s job (BACKLOG.md's DB-3), not the
engine's. Recognizing it as a plain FLAG keyword lets a card whose only
ability is this reach `MODELED` instead of parking forever.

Scoped to the keyword clause only, per the ticket: several Doctor's-
companion cards (e.g. Rose Noble's "whenever you cast a Doctor spell or
creature spell with doctor's companion, draw a card.") also carried a
separate, unrelated bespoke ability body that this clause alone didn't
unlock — that gap (referencing the keyword as a card-quality filter, both
in a cast-trigger condition and a library-search criterion) closed under
PAR-75; see `test_par75_doctors_companion_family.py`.

Reference: mtg_analyzer/parser/oracle/catalogue/keywords.py (`_TABLE`).
"""

from __future__ import annotations

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import is_keyword_line


def test_doctors_companion_keyword_line_is_claimed():
    assert is_keyword_line("doctor's companion")


def test_barbara_wright_shaped_card_is_modeled():
    # Barbara Wright's only ability is the bare keyword line.
    card = Card(
        id="Test Companion", name="Test Companion",
        type_line="Legendary Creature — Human", is_creature=True, power=1, toughness=1,
        oracle_text="Doctor's companion (You can have two commanders if the other is the Doctor.)",
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_doctors_companion_combines_with_another_flag_keyword():
    # Nardole, Resourceful Cyborg-shaped: Undying + Doctor's companion, both
    # plain FLAG keyword lines, must both be claimed for the card to model.
    card = Card(
        id="Test Cyborg", name="Test Cyborg",
        type_line="Legendary Creature — Cyborg", is_creature=True, power=1, toughness=1,
        oracle_text="Undying\nDoctor's companion (You can have two commanders if the other is the Doctor.)",
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_a_trigger_referencing_doctors_companion_as_a_filter_is_modeled():
    # Rose Noble: the bare keyword line was already claimed by PAR-69; the
    # separate trigger clause quoting "doctor's companion" as a card-quality
    # filter closed under PAR-75 (`test_par75_doctors_companion_family.py`).
    card = Card(
        id="Test Rose Noble", name="Test Rose Noble",
        type_line="Legendary Creature — Human", is_creature=True, power=2, toughness=2,
        oracle_text=(
            "Whenever you cast a Doctor spell or creature spell with doctor's "
            "companion, draw a card.\n"
            "Doctor's companion (You can have two commanders if the other is the Doctor.)"
        ),
    )
    result = parse_oracle(card)
    assert result.modeled

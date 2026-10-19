"""BUG-7 -- the draw-per-opponent-with-more-cards row is controller-only.

The builder emits a plain controller `draw` and "than you" is relative to the controller, so a third-person
subject ("each opponent / target player draws ...") must not be claimed by this row.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause

TAIL = "a card for each opponent who has more cards in their hand than you"


@pytest.mark.parametrize("clause", [f"then you draw {TAIL}", f"you draw {TAIL}", f"draw {TAIL}"])
def test_controller_forms_still_claimed(clause):
    specs = match_clause(clause)
    assert specs and specs[0].type == "draw"
    assert specs[0].params["count"]["selector"] == "opponents_with_more_cards_in_hand"


@pytest.mark.parametrize("subject", ["each opponent", "target player", "target opponent", "that player",
                                     "each player", "then that player", "then"])
def test_third_person_subject_not_claimed(subject):
    assert not match_clause(f"{subject} draws {TAIL}")

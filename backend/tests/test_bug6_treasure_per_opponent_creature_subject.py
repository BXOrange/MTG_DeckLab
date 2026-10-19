"""BUG-6 -- the Treasure-per-opponent-creature row is controller-only.

The builder always emits the controller as creator and "your opponents" in the count is relative to the controller,
so a third-person subject ("that player creates ...") must stay unclaimed instead of paying the controller.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause

TAIL = "treasure token for each creature your opponents control"


@pytest.mark.parametrize("clause", [
    f"then you create a tapped {TAIL}",
    f"you create a {TAIL}",
    f"create a {TAIL}",
])
def test_controller_forms_still_claimed(clause):
    specs = match_clause(clause)
    assert specs and specs[0].type == "create_token"
    assert specs[0].params["count_selector"] == "creatures_opponents_control"
    assert "creators" not in specs[0].params  # controller is the default creator


@pytest.mark.parametrize("subject", ["that player", "each opponent", "target opponent", "each player", "then", "then that player"])
def test_third_person_subject_not_claimed(subject):
    assert not match_clause(f"{subject} creates a {TAIL}")
    assert not match_clause(f"{subject} creates a tapped {TAIL}")


from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle import parse_oracle

EDICT = "Each player chooses up to two creatures they control, then sacrifices the rest. "


def _sorcery(oracle):
    return Card(id="x", name="X", type_line="Sorcery", oracle_text=oracle, mana_cost_string="{0}",
                converted_mana_cost=0, is_sorcery=True)


def test_covetous_elegy_shape_stays_modeled():
    assert parse_oracle(_sorcery(EDICT + "Then you create a tapped Treasure token for each creature your opponents control.")).modeled


@pytest.mark.parametrize("tail", [
    "That player creates a Treasure token for each creature your opponents control.",
    "Then that player creates a tapped Treasure token for each creature your opponents control.",
])
# "Each opponent creates ..." is not in this list on purpose: a separate, correct bind row models it with
# creators="each_opponent" (the Treasures go to the opponents).
def test_third_person_edict_tail_is_unmodeled(tail):
    assert not parse_oracle(_sorcery(EDICT + tail)).modeled

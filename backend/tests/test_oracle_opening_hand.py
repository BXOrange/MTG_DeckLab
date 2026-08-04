"""Tests for RULE 103.6a's "begin the game with it on the battlefield"
opening-hand permission recognition (`parser/oracle/catalogue/
opening_hand.py`) — the single source of truth the coverage gate (`gate.py`)
and the engine (`game/ability_catalogue.opening_hand_battlefield_permission`)
both consult, so the shapes claimed and the shapes resolved can never drift
apart (PLR-11).
"""

from mtg_analyzer.game.ability_catalogue import opening_hand_battlefield_permission
from mtg_analyzer.models.card import Card
from mtg_analyzer.parser.oracle import MODELED, UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.catalogue.opening_hand import (
    opening_hand_battlefield_permission_line,
)

# ---------------------------------------------------------------------------
# opening_hand_battlefield_permission_line — direct clause-shape classification
# ---------------------------------------------------------------------------


def test_this_card_it_shape():
    line = "if this card is in your opening hand, you may begin the game with it on the battlefield."
    assert opening_hand_battlefield_permission_line(line) is True


def test_self_name_folded_subject_with_pronoun():
    # Quicksilver, Brash Blur's own printed name folds to "~"; the pronoun
    # is "him" rather than "it".
    line = "if ~ is in your opening hand, you may begin the game with him on the battlefield."
    assert opening_hand_battlefield_permission_line(line) is True


def test_missing_trailing_period_still_matches():
    line = "if this card is in your opening hand, you may begin the game with it on the battlefield"
    assert opening_hand_battlefield_permission_line(line) is True


def test_unrelated_line_is_not_claimed():
    assert opening_hand_battlefield_permission_line("you have hexproof.") is False


def test_gemstone_caverns_shaped_extra_clause_is_not_claimed():
    # A genuinely different, conditional/costed shape — not the plain
    # Leyline-cycle sentence — must stay unclaimed rather than silently
    # dropping the "not the starting player"/counter/cost tail.
    line = (
        "if this card is in your opening hand and you're not the starting "
        "player, you may begin the game with ~ on the battlefield with a "
        "luck counter on it."
    )
    assert opening_hand_battlefield_permission_line(line) is False


def test_graveyard_variant_is_not_claimed():
    # Buried Ogre-shaped: a different destination (graveyard, not
    # battlefield) than this clause recognises.
    line = "you may begin the game with ~ in your graveyard."
    assert opening_hand_battlefield_permission_line(line) is False


# ---------------------------------------------------------------------------
# opening_hand_battlefield_permission(card) / coverage-gate integration
# ---------------------------------------------------------------------------


def leyline(name, extra_lines=""):
    oracle = "If this card is in your opening hand, you may begin the game with it on the battlefield."
    if extra_lines:
        oracle = f"{oracle}\n{extra_lines}"
    return Card(id=name, name=name, type_line="Enchantment", mana_cost_string="{2}{W}", oracle_text=oracle)


def test_card_level_permission_reads_true():
    card = leyline("Test Leyline")
    assert opening_hand_battlefield_permission(card) is True


def test_card_level_permission_false_when_absent():
    card = Card(id="Plain", name="Plain", type_line="Enchantment", oracle_text="You have hexproof.")
    assert opening_hand_battlefield_permission(card) is False


def test_solo_clause_is_fully_modeled():
    card = leyline("Solo Leyline")
    result = parse_oracle(card)
    assert result.coverage == MODELED
    assert result.unclaimed == []


def test_claimed_alongside_another_modeled_static():
    card = leyline("Sanctity-shaped", extra_lines="You have hexproof.")
    result = parse_oracle(card)
    assert result.coverage == MODELED
    assert result.unclaimed == []


def test_does_not_mask_other_unclaimed_lines():
    # Claiming this line can't paper over a genuinely unrelated gap
    # elsewhere on the card (fail-closed, docs/09) — the whole point of the
    # gate being all-or-nothing.
    card = leyline("Half Leyline", extra_lines="Bargle the frobnicator twice.")
    result = parse_oracle(card)
    assert result.coverage == UNMODELED
    assert "bargle the frobnicator twice." in result.unclaimed
    assert not any("opening hand" in line for line in result.unclaimed)

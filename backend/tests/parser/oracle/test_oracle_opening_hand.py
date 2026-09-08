"""Tests for RULE 103.6 pregame setup permission recognition
(`parser/oracle/catalogue/opening_hand.py`) — the single source of truth
the coverage gate (`gate.py`) and the engine (`game/ability_catalogue.
opening_hand_battlefield_permission`/`pregame_setup_permission`) both
consult, so the shapes claimed and the shapes resolved can never drift
apart (PLR-11 and its own follow-up).
"""

from mtg_analyzer.game.ability_catalogue import (
    opening_hand_battlefield_permission,
    pregame_setup_permission,
)
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle import MODELED, UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.catalogue.opening_hand import (
    opening_hand_battlefield_conditional_permission_line,
    opening_hand_battlefield_permission_line,
    opening_hand_graveyard_permission_line,
    PregameSetupPermission,
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


def test_gemstone_caverns_shaped_extra_clause_is_not_claimed_here():
    # A genuinely different, conditional/costed shape — not the plain
    # Leyline-cycle sentence this narrow function recognises. Claimed
    # instead by `opening_hand_battlefield_conditional_permission_line`
    # below (still correctly *un*claimed by the plain one, so a real
    # Gemstone Caverns doesn't double-count).
    line = (
        "if this card is in your opening hand and you're not the starting "
        "player, you may begin the game with ~ on the battlefield with a "
        "luck counter on it. if you do, exile a card from your hand."
    )
    assert opening_hand_battlefield_permission_line(line) is False


def test_graveyard_variant_is_not_claimed_here():
    # Buried Ogre-shaped: a different destination (graveyard, not
    # battlefield) than this clause recognises. Claimed instead by
    # `opening_hand_graveyard_permission_line` below.
    line = "you may begin the game with ~ in your graveyard. if you do, you lose 1 life."
    assert opening_hand_battlefield_permission_line(line) is False


# ---------------------------------------------------------------------------
# opening_hand_battlefield_conditional_permission_line — Gemstone Caverns
# ---------------------------------------------------------------------------


def test_gemstone_caverns_shape_is_claimed():
    line = (
        "if this card is in your opening hand and you're not the starting "
        "player, you may begin the game with ~ on the battlefield with a "
        "luck counter on it. if you do, exile a card from your hand."
    )
    assert opening_hand_battlefield_conditional_permission_line(line) is True


def test_gemstone_caverns_shape_by_printed_name_is_claimed():
    # Real cards refer to themselves by name here, not a pronoun — the
    # printed name is folded to "~" by `normalize` before this ever sees it.
    line = (
        "if this card is in your opening hand and you're not the starting "
        "player, you may begin the game with ~ on the battlefield with a "
        "luck counter on it. if you do, exile a card from your hand."
    )
    assert opening_hand_battlefield_conditional_permission_line(line) is True


def test_gemstone_caverns_without_the_condition_is_not_claimed():
    # Dropping "and you're not the starting player" is a genuinely weaker
    # permission this regex must not silently accept.
    line = (
        "if this card is in your opening hand, you may begin the game "
        "with ~ on the battlefield with a luck counter on it. if you do, "
        "exile a card from your hand."
    )
    assert opening_hand_battlefield_conditional_permission_line(line) is False


def test_gemstone_caverns_without_the_exile_tail_is_not_claimed():
    # Missing the mandatory cost this shape's engine handling assumes.
    line = (
        "if this card is in your opening hand and you're not the starting "
        "player, you may begin the game with ~ on the battlefield with a "
        "luck counter on it."
    )
    assert opening_hand_battlefield_conditional_permission_line(line) is False


# ---------------------------------------------------------------------------
# opening_hand_graveyard_permission_line — Buried Ogre
# ---------------------------------------------------------------------------


def test_buried_ogre_shape_is_claimed():
    line = "you may begin the game with ~ in your graveyard. if you do, you lose 1 life."
    assert opening_hand_graveyard_permission_line(line) is True


def test_buried_ogre_without_the_life_loss_tail_is_not_claimed():
    line = "you may begin the game with ~ in your graveyard."
    assert opening_hand_graveyard_permission_line(line) is False


# ---------------------------------------------------------------------------
# pregame_setup_permission(card) — the general, card-level entry point
# ---------------------------------------------------------------------------


def gemstone_caverns(name="Test Gemstone Caverns"):
    return Card(
        id=name,
        name=name,
        type_line="Land",
        oracle_text=(
            f"If this card is in your opening hand and you're not the "
            f"starting player, you may begin the game with {name} on the "
            f"battlefield with a luck counter on it. If you do, exile a "
            f"card from your hand.\n"
            f"{{T}}: Add {{C}}. If {name} has a luck counter on it, "
            f"instead add one mana of any color."
        ),
    )


def buried_ogre(name="Test Buried Ogre"):
    return Card(
        id=name,
        name=name,
        type_line="Creature — Ogre",
        oracle_text=f"You may begin the game with {name} in your graveyard. If you do, you lose 1 life.",
    )


def test_pregame_setup_permission_plain_shape():
    assert pregame_setup_permission(leyline("Plain Leyline")) == PregameSetupPermission(
        destination="battlefield"
    )


def test_pregame_setup_permission_gemstone_caverns_shape():
    permission = pregame_setup_permission(gemstone_caverns())
    assert permission == PregameSetupPermission(
        destination="battlefield",
        condition="not_starting_player",
        counter_type="luck",
        counter_count=1,
        cost_kind="exile_hand_card",
    )


def test_pregame_setup_permission_buried_ogre_shape():
    permission = pregame_setup_permission(buried_ogre())
    assert permission == PregameSetupPermission(
        destination="graveyard", cost_kind="lose_life", cost_amount=1
    )


def test_pregame_setup_permission_none_when_absent():
    card = Card(id="Plain", name="Plain", type_line="Enchantment", oracle_text="You have hexproof.")
    assert pregame_setup_permission(card) is None


def test_gemstone_caverns_is_fully_modeled():
    result = parse_oracle(gemstone_caverns())
    assert result.coverage == MODELED
    assert result.unclaimed == []


def test_buried_ogre_is_fully_modeled():
    result = parse_oracle(buried_ogre())
    assert result.coverage == MODELED
    assert result.unclaimed == []


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

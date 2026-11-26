"""BUG-86: the card-level coverage verdict reads every half the engine binds, not the front face alone.

``parse_oracle`` reads a card's front face; a split / aftermath / fuse, Adventure, modal DFC, transform or prepare card
binds its other half as a card of its own (RULE 709.3, 716.2b, 712.8b, 712.6, 723.3c), so a MODELED front over an
UNMODELED back left the card counted as playable with an unbound half. `card_registry.card_coverage` / `is_card_covered`
are the one rule; Rooms (RULE 709.5) and flip cards (RULE 710) were already merged inside `parse_oracle`.
"""
import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import card_registry
from mtg_analyzer.game.card_registry import card_coverage, is_card_covered
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle import MODELED, UNMODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase

_FRONT = "Destroy target creature."
_MODELED_BACK = "Draw a card."
#: For Mirrodin! still lacks engine behavior, so it keeps this synthetic back half unmodeled.
_UNMODELED_BACK = "For Mirrodin!"
_LAYOUTS = {
    # layout -> (front type line, back type line)
    "split": ("Sorcery", "Sorcery"),
    "adventure": ("Sorcery", "Sorcery — Adventure"),
    "modal_dfc": ("Sorcery", "Sorcery"),
    "transform": ("Sorcery", "Sorcery"),
    "prepare": ("Sorcery", "Sorcery"),
}


def _two_faced(layout, back_text, name="Zzz Front // Zzz Back", **extra):
    front_type, back_type = _LAYOUTS[layout]
    return Card(
        id=name, name=name, layout=layout, type_line=front_type, oracle_text=_FRONT, is_sorcery=True,
        back_name="Zzz Back", back_type_line=back_type, back_oracle_text=back_text, **extra,
    )


@pytest.mark.parametrize("layout", sorted(_LAYOUTS))
def test_unmodeled_back_half_makes_the_card_unmodeled(layout):
    card = _two_faced(layout, _UNMODELED_BACK)
    assert parse_oracle(card).coverage == MODELED  # the front alone is what parse_oracle reads
    result = card_coverage(card)
    assert result.coverage == UNMODELED
    assert any("for mirrodin" in line.lower() for line in result.unclaimed)
    assert not is_card_covered(card)


@pytest.mark.parametrize("layout", sorted(_LAYOUTS))
def test_fully_modeled_halves_stay_modeled(layout):
    card = _two_faced(layout, _MODELED_BACK)
    assert card_coverage(card).coverage == MODELED
    assert is_card_covered(card)


def test_single_faced_card_is_unchanged():
    card = Card(id="x", name="Zzz Solo", type_line="Sorcery", oracle_text=_FRONT, is_sorcery=True)
    assert card_coverage(card).coverage == MODELED


def test_flip_card_back_is_judged_inside_parse_oracle_not_twice():
    """A flip half is merged by `parse_oracle` (RULE 710); `card_coverage` adds nothing on top."""
    card = Card(id="f", name="Zzz Flip", layout="flip", type_line="Creature — Human", is_creature=True,
                oracle_text="Flying", back_name="Zzz Flipped", back_type_line="Creature — Spirit",
                back_oracle_text=_UNMODELED_BACK, power=1, toughness=1)
    assert card_coverage(card).coverage == parse_oracle(card).coverage


def test_a_hand_authored_back_half_counts(monkeypatch):
    card = _two_faced("split", _UNMODELED_BACK)
    monkeypatch.setitem(card_registry._REGISTRY, "zzz back", lambda: [])
    assert card_coverage(card).coverage == MODELED
    assert is_card_covered(card)


def test_a_hand_authored_whole_card_is_trusted(monkeypatch):
    card = _two_faced("adventure", _UNMODELED_BACK)
    monkeypatch.setitem(card_registry._REGISTRY, "zzz front", lambda: [])
    assert is_card_covered(card)


def test_the_card_list_badge_uses_the_same_rule():
    from mtg_analyzer.api.cards import coverage_for

    assert coverage_for(_two_faced("split", _UNMODELED_BACK))["modeled"] is False
    assert coverage_for(_two_faced("split", _MODELED_BACK))["modeled"] is True


def test_claim_fame_is_modeled_with_aftermath():
    card = CardDatabase(DB_PATH).get_card("Claim // Fame")
    if card is None:
        pytest.skip("Claim // Fame is not in the local card cache")
    assert parse_oracle(card).coverage == MODELED  # Claim alone
    assert is_card_covered(card)

"""PAR-86 — choose graveyard cards from a targeted player's graveyard."""

from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.models.cards.card import Card


def test_targeted_graveyard_shuffle_parses():
    assert parse_effect_body(
        "target player shuffles up to 4 target cards from their graveyard into their library."
    ) == [EffectSpec("shuffle_target_graveyard_cards_into_library", {"count_max": 4})]


def test_targeted_graveyard_shuffle_does_not_claim_the_own_graveyard_form():
    assert parse_effect_body(
        "shuffle up to 4 target cards from your graveyard into your library."
    ) is None


def test_dwell_on_the_past_is_modeled():
    card = Card(id="Dwell on the Past", name="Dwell on the Past", type_line="Instant",
                is_instant=True,
                oracle_text="Target player shuffles up to four target cards from their graveyard into their library.")
    assert parse_oracle(card).modeled

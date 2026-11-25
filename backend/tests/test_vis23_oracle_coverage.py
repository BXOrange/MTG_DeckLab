from mtg_analyzer.api.cards import _unmodeled_oracle_lines, list_cards
from mtg_analyzer.models.cards.card import Card


def test_card_cache_marks_only_the_unmodeled_back_ability():
    card = Card(
        id="vis23",
        name="Test Front // Test Back",
        layout="split",
        type_line="Sorcery",
        is_sorcery=True,
        oracle_text="Destroy target creature.",
        back_name="Test Back",
        back_type_line="Sorcery",
        back_oracle_text="Draw a card.\nFor Mirrodin!",
    )

    class Cache:
        def list_cards(self):
            return [card]

    [result] = list_cards(scope="all", database=Cache(), decks=None)

    assert result["coverage"]["modeled"] is False
    assert result["coverage"]["unmodeled_lines"] == {"back": [1]}
    assert result["back_oracle_text"] == card.back_oracle_text


def test_unclaimed_fragments_only_mark_unambiguous_original_lines():
    card = Card(
        id="vis23-ambiguous",
        name="Test Guardian",
        type_line="Creature",
        oracle_text=(
            "Flying\n"
            "{T}: Add one mana of any color. That spell can't be countered.\n"
            "When Test Guardian attacks, draw a card."
        ),
        back_name="Test Guardian Back",
        back_oracle_text="Flying",
    )

    assert _unmodeled_oracle_lines(card, [
        "flying",
        "that spell can't be countered.",
        "when ~ attacks, draw a card.",
        "synthetic diagnostic",
    ]) == {"front": [1, 2]}

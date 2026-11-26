from mtg_analyzer.api.cards import _unmodeled_oracle_marks, list_cards
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

    assert _unmodeled_oracle_marks(card, [
        "flying",
        "that spell can't be countered.",
        "when ~ attacks, draw a card.",
        "synthetic diagnostic",
    ]) == {
        "front": {
            1: (len("{T}: Add one mana of any color. "), len(card.oracle_text.splitlines()[1])),
            2: None,
        },
    }


def test_card_cache_marks_only_the_unmodeled_sentence_of_starfall_invocation():
    wipe = "Destroy all creatures. "
    rider = (
        "If the gift was promised, return a creature card put into your graveyard "
        "this way to the battlefield under your control."
    )
    card = Card(
        id="vis23-starfall",
        name="Starfall Invocation",
        type_line="Sorcery",
        is_sorcery=True,
        oracle_text=f"Gift a card\n{wipe}{rider}",
        keywords=["Gift"],
    )

    class Cache:
        def list_cards(self):
            return [card]

    [result] = list_cards(scope="all", database=Cache(), decks=None)
    coverage = result["coverage"]
    assert coverage["modeled"] is False
    assert coverage["unmodeled_lines"] == {"front": [1]}
    assert coverage["unmodeled_ranges"] == {"front": {1: (len(wipe), len(wipe + rider))}}
    assert coverage["unclaimed"] == [(wipe + rider).lower()]

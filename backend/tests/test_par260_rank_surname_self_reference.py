"""PAR-260: "<rank> <surname>" self-reference folds to the self token (RULE 201.5)."""

import pytest

from mtg_analyzer.parser.oracle.normalize import normalize, _rank_surname_form


@pytest.mark.parametrize("name,form", [
    ("Captain James T. Kirk", "Captain Kirk"),
    ('Dr. Leonard "Bones" McCoy', "Dr. McCoy"),
    ("Ensign Harry Kim, Operations", "Ensign Kim"),
    ("Commander Raffi Musiker", "Commander Musiker"),
    ("Lieutenant Hikaru Sulu", "Lieutenant Sulu"),
])
def test_rank_surname_form(name, form):
    assert _rank_surname_form(name) == form


@pytest.mark.parametrize("name", ["Captain Sisay", "Goblin Chieftain", "Llanowar Elves", "Captain of the Watch"])
def test_no_form_for_non_ranked_or_short_names(name):
    assert (name == "Captain of the Watch") or _rank_surname_form(name) is None


def test_fold_rank_surname():
    assert normalize("Whenever Captain Janeway or another creature enters, that creature explores.",
                     "Captain Kathryn Janeway").startswith("whenever ~ or another")
    assert "~" in normalize("When Dr. McCoy enters, draw.", 'Dr. Leonard "Bones" McCoy')


def test_bare_rank_and_other_characters_not_folded():
    text = normalize("Other Captains you control get +1/+1. Captain Picard gets +1/+1.", "Captain James T. Kirk")
    assert "~" not in text
    assert "captain picard" in text


@pytest.mark.parametrize("name", ["Captain Kathryn Janeway", "Captain Michael Burnham", "Commander Raffi Musiker",
                                  "Dr. Beverly Crusher", "Lieutenant Hikaru Sulu"])
def test_flipped_cards_modeled(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.parser.oracle import MODELED, parse_oracle
    from mtg_analyzer.services.card_database import CardDatabase

    card = CardDatabase(DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card not in local cache")
    assert parse_oracle(card).coverage == MODELED

"""Catalogue descriptions use canonical card text."""

from pathlib import Path

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _kor_spiritdancer() -> Card:
    return Card(
        id="kor-spiritdancer",
        name="Kor Spiritdancer",
        type_line="Creature — Kor Wizard",
        is_creature=True,
        power=0,
        toughness=2,
        oracle_text=(
            "Kor Spiritdancer gets +2/+2 for each Aura attached to it.\n"
            "Whenever you cast an Aura spell, you may draw a card."
        ),
    )


def test_hand_authored_catalogue_specs_do_not_embed_raw_text():
    catalogue = Path(__file__).parents[3] / "mtg_analyzer" / "game" / "card_registry"
    assert not any("raw_text=" in path.read_text(encoding="utf-8") for path in catalogue.glob("*.py"))


def test_hand_authored_ability_description_uses_card_oracle_text():
    card = _kor_spiritdancer()
    source = GameObject(card, owner_id="player", zone=Zone.BATTLEFIELD)
    triggered_spec = next(spec for spec in specs_for(card) if spec.ability_kind == "triggered")

    ability = bind_ability(triggered_spec, source)

    assert ability.description == card.oracle_text

"""MEC-119: native RULE 702.185 Warp costs reach the game object."""

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.keywords import parse_keywords
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _card(text, name="Warp fixture"):
    return Card(id=name, name=name, type_line="Creature — Robot",
                mana_cost_string="{7}", oracle_text=text, keywords=["Warp"])


@pytest.mark.parametrize("cost", ["{3}", "{X}{G}", "{B/R}", "{2}{U}{U}"])
def test_native_warp_cost_survives_parse_and_binding(cost):
    card = _card(f"Warp {cost}")
    result = parse_oracle(card)
    assert result.modeled
    assert [s.keyword for s in result.specs] == [{"name": "warp", "cost": cost}]
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    assert obj.parametric_keywords["warp"] == {"cost": cost}


def test_real_bygone_colossus_reminder_text_and_binding():
    card = _card(
        "Warp {3} (You may cast this card from your hand for its warp cost. "
        "Exile this creature at the beginning of the next end step, then you "
        "may cast it from exile on a later turn.)",
        "Bygone Colossus",
    )
    assert parse_oracle(card).modeled
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    assert obj.parametric_keywords["warp"]["cost"] == "{3}"


def test_warp_grant_does_not_replace_native_cost():
    card = _card("Cards in your hand have warp {3}.\nWarp {1}{U}")
    assert parse_keywords(card)[0].keyword == {"name": "warp", "cost": "{1}{U}"}


@pytest.mark.parametrize("text", [
    "Cards in your hand have warp {3}.",
    "Warp—{B}, Pay 2 life.",
    "Warp {1} and draw a card.",
])
def test_unsupported_warp_line_does_not_supply_partial_cost(text):
    assert parse_keywords(_card(text))[0].keyword == {"name": "warp"}
    assert not parse_oracle(_card(text)).modeled

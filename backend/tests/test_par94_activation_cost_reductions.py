"""PAR-94's closed parser route for per-unit activation-cost discounts."""

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _parse(body: str):
    card = Card(
        id="par94", name="Test Relic", type_line="Artifact",
        oracle_text="{5}, {T}: Draw a card. " + body,
    )
    result = parse_oracle(card)
    assert result.modeled is True
    assert result.specs[0].effects == [EffectSpec("draw", {"count": 1})]
    return result.specs[0].cost["dynamic_reduction"]


def test_existing_selector_forms_are_folded_into_activation_cost():
    assert _parse(
        "This ability costs {1} less to activate for each basic land type among lands you control."
    ) == {"count_selector": "basic_land_types_among_lands_you_control", "generic_per": 1}
    assert _parse(
        "This ability costs {2} less to activate for each creature card in your graveyard."
    ) == {"count_selector": "creature_cards_in_your_graveyard", "generic_per": 2}
    assert _parse(
        "This ability costs {1} less to activate for each oil counter on this artifact."
    ) == {"count_selector": "source_oil_counters", "generic_per": 1}


def test_subtype_and_tail_forms_are_folded_without_claiming_unknown_forms():
    assert _parse(
        "This ability costs {1} less to activate for each Shrine you control."
    ) == {"count_selector": "permanents_you_control_of_subtype_shrine", "generic_per": 1}
    assert _parse(
        "This ability costs {1} less to activate for each other Town you control."
    ) == {"count_selector": "other_permanents_you_control_of_subtype_town", "generic_per": 1}
    assert _parse(
        "This ability costs {1} less to activate for each modified creature you control."
    ) == {"count_selector": "modified_creatures_you_control", "generic_per": 1}
    assert _parse(
        "This ability costs {1} less to activate for each creature with power 4 or greater your opponents control."
    ) == {"count_selector": "creatures_opponents_control_with_power_ge_4", "generic_per": 1}

    unknown = Card(
        id="unknown", name="Unknown", type_line="Artifact",
        oracle_text="{5}, {T}: Draw a card. This ability costs {X} less to activate, where X is your devotion to blue.",
    )
    assert parse_oracle(unknown).modeled is False


def test_conditional_graveyard_mana_value_discount_is_a_live_gate():
    reduction = _parse(
        "This ability costs {3} less to activate if there are 5 or more mana values among cards in your graveyard."
    )
    assert reduction == {
        "generic_per": 3,
        "active_if": {"kind": "distinct_mana_values_in_graveyard_at_least", "min": 5},
    }

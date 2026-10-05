"""PAR-94's closed parser route for per-unit activation-cost discounts.

PAR-120 (PARSER_VERSION 470) retired six of `_ACTIVATION_COST_REDUCTION_
SELECTORS`' original fourteen entries (plus a redundant `island`-only land
fallback) in favour of the shared `count_phrase` grammar, which already
reached the identical phrases — the remaining eight (a distinct-land-type
count, the "instant and sorcery" union idiom, a two-card-type union, "other
`<X>`"/"modified `<X>`" qualifiers, and a `+1/+1` counter *count*, a
different measurement axis) genuinely aren't `{zone, of, filter}` selectors
and stay named. The power-qualified opponent-creature row now also reaches
the grammar's own `min_power` filter key instead of a bespoke selector
string, proven to count identically on a real board
(`test_par120_count_phrase.py`).
"""

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
    ) == {
        "count_selector": {"zone": "graveyard", "of": "you", "filter": {"card_type": "creature"}},
        "generic_per": 2,
    }
    assert _parse(
        "This ability costs {1} less to activate for each oil counter on this artifact."
    ) == {"count_selector": "source_oil_counters", "generic_per": 1}


def test_subtype_and_tail_forms_are_folded_without_claiming_unknown_forms():
    assert _parse(
        "This ability costs {1} less to activate for each Shrine you control."
    ) == {
        "count_selector": {"zone": "battlefield", "of": "you", "filter": {"subtype": "shrine"}},
        "generic_per": 1,
    }
    assert _parse(
        "This ability costs {1} less to activate for each other Town you control."
    ) == {"count_selector": {"zone": "battlefield", "of": "you", "filter": {"subtype": "town", "not_reference": True}}, "generic_per": 1}
    assert _parse(
        "This ability costs {1} less to activate for each modified creature you control."
    ) == {"count_selector": "modified_creatures_you_control", "generic_per": 1}
    assert _parse(
        "This ability costs {1} less to activate for each creature with power 4 or greater your opponents control."
    ) == {
        "count_selector": {
            "zone": "battlefield", "of": "opponents",
            "filter": {"card_type": "creature", "min_power": 4},
        },
        "generic_per": 1,
    }

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


def test_a_basic_land_type_reaches_the_grammar_without_its_own_fallback():
    # PAR-120: the old hand-rolled `island`-only regex fallback is gone —
    # the shared grammar's own subtype recognition reaches it (and any
    # other basic land type) generically now.
    assert _parse(
        "This ability costs {1} less to activate for each Island you control."
    ) == {
        "count_selector": {"zone": "battlefield", "of": "you", "filter": {"subtype": "island"}},
        "generic_per": 1,
    }


def test_min_power_selector_counts_the_same_as_the_old_named_string():
    from mtg_analyzer.game import continuous
    from mtg_analyzer.models.game.game_object import GameObject, Zone
    from mtg_analyzer.models.game.game_state import GameState
    from mtg_analyzer.models.game.player import Player

    state = GameState(players=[Player(id="p1", name="A", life=20), Player(id="p2", name="B", life=20)])
    for name, power in (("c1", 3), ("c2", 4), ("c3", 5)):
        obj = GameObject(
            Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
                 power=power, toughness=power),
            owner_id="p2", zone=Zone.BATTLEFIELD,
        )
        obj.controller_id = "p2"
        state.add_to_battlefield(obj)
    legacy = continuous.count_selector(state, "p1", "creatures_opponents_control_with_power_ge_4")
    structured = continuous.count_selector(state, "p1", {
        "zone": "battlefield", "of": "opponents", "filter": {"card_type": "creature", "min_power": 4},
    })
    assert legacy == structured == 2

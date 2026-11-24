"""PAR-284: amount host slots -- "create a number of <tokens> equal to <amount>" and "search your library for up to X
<cards>, where X is <amount>" (RULE 107.3, 111.2, 701.19a).

Both verbs already take a literal X; what was missing was reaching the shared "where X is" grammar from the
"a number of ... equal to" spelling and accepting the definition mid-sentence in the search sentence.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.game.binding.core import attach_to_object
from tests.test_par284_this_way_windows import _card, _cast, _engine


def _bound(oracle):
    specs = parse_effect_body(oracle)
    assert specs is not None and [s.type for s in specs] == ["bind"], specs
    return specs[0].params


def test_create_a_number_of_tokens_equals_the_where_x_reading():
    number = _bound("create a number of 1/1 green insect creature tokens with flying equal to the number of card types "
                    "among cards in your graveyard.")
    where = _bound("create x 1/1 green insect creature tokens with flying, where x is the number of card types "
                   "among cards in your graveyard.")
    assert number == where
    assert number["amount"]["selector"]["distinct"] == "card_type"
    assert number["effects"][0]["params"]["count"] == "$n"


def test_search_where_x_midsentence_binds_the_count():
    params = _bound("search your library for up to x basic land cards, where x is the number of lands you control, "
                    "put them onto the battlefield tapped, then shuffle.")
    assert params["effects"][0]["type"] == "search"
    assert params["effects"][0]["params"]["count"] == "$n"
    sentence_break = _bound("search your library for up to x basic land cards, where x is the number of lands you "
                            "control. put those cards onto the battlefield tapped, then shuffle.")
    assert sentence_break == params


def test_different_powers_among_is_a_distinct_selector():
    selector = _bound("search your library for up to x basic land cards, where x is the number of different powers "
                      "among creatures you control, put them onto the battlefield tapped, then shuffle.")["amount"]["selector"]
    assert selector["distinct"] == "power"


@pytest.mark.parametrize("oracle", [
    "search your library for up to x basic land cards, where x is your speed, put them onto the battlefield tapped.",
    "create a number of 1/1 insect creature tokens equal to the moon's phase.",
])
def test_unknown_amounts_stay_unclaimed(oracle):
    assert parse_effect_body(oracle) is None


def test_real_cards_are_modeled():
    for name, type_line, oracle in [
        ("Broodspinner", "Creature — Insect",
         "{4}{B}{G}, {T}, Sacrifice this creature: Create a number of 1/1 black and green Insect creature tokens with "
         "flying equal to the number of card types among cards in your graveyard."),
        ("Boundless Realms", "Sorcery",
         "Search your library for up to X basic land cards, where X is the number of lands you control, put them onto "
         "the battlefield tapped, then shuffle."),
        ("Traverse the Outlands", "Sorcery",
         "Search your library for up to X basic land cards, where X is the greatest power among creatures you control. "
         "Put those cards onto the battlefield tapped, then shuffle."),
    ]:
        result = parse_oracle(_card(name, type_line, oracle, is_sorcery=type_line == "Sorcery"))
        assert result.modeled, (name, result.unclaimed)


def test_boundless_realms_fetches_one_land_per_land_you_control():
    eng = _engine()
    p1 = eng.state.players[0]
    for i in range(2):  # two lands in play: X = 2
        land = GameObject(_card(f"Home{i}", "Land"), owner_id="p1", zone=Zone.BATTLEFIELD)
        land.controller_id = "p1"
        eng.state.battlefield.append(land)
    for i in range(4):
        p1.library.append(GameObject(_card(f"Forest{i}", "Basic Land - Forest"), owner_id="p1", zone=Zone.LIBRARY))
    before = len(eng.state.battlefield)
    _cast(eng, "Search your library for up to X basic land cards, where X is the number of lands you control, "
               "put them onto the battlefield tapped, then shuffle.")
    picked = 0
    while eng.state.pending_choice is not None and picked < 10:  # one pick per card; "up to X" ends at X
        eng.rules.resolve_choice(eng.state.pending_choice["eligible"][0]["instance_id"])
        picked += 1
    assert picked == 2
    assert len(eng.state.battlefield) - before == 2


def test_broodspinner_tokens_equal_distinct_card_types_in_graveyard():
    eng = _engine()
    p1 = eng.state.players[0]
    for name, type_line, flag in (("G1", "Creature - Bear", {"is_creature": True, "power": 1, "toughness": 1}),
                                  ("G2", "Land", {}), ("G3", "Creature - Elk", {"is_creature": True, "power": 1, "toughness": 1})):
        p1.graveyard.append(GameObject(_card(name, type_line, **flag), owner_id="p1", zone=Zone.GRAVEYARD))
    before = len(eng.state.battlefield)
    _cast(eng, "Create a number of 1/1 black and green Insect creature tokens with flying equal to the number of "
               "card types among cards in your graveyard.")
    assert len(eng.state.battlefield) - before == 2  # creature + land: two types among three cards


def test_goblin_gathering_counts_named_cards_in_graveyard():
    """Gained by the same widening: "equal to two plus the number of cards named ~ in your graveyard"."""
    eng = _engine()
    p1 = eng.state.players[0]
    p1.graveyard.append(GameObject(_card("Probe Spell", "Sorcery", is_sorcery=True), owner_id="p1", zone=Zone.GRAVEYARD))
    before = len(eng.state.battlefield)
    _cast(eng, "Create a number of 1/1 red Goblin creature tokens equal to two plus the number of cards named "
               "Probe Spell in your graveyard.")
    assert len(eng.state.battlefield) - before == 3


def test_lacerate_flesh_blood_tokens_equal_excess_damage():
    eng = _engine()
    victim = GameObject(_card("Victim", "Creature - Bear", is_creature=True, power=1, toughness=1),
                        owner_id="p2", zone=Zone.BATTLEFIELD)
    victim.controller_id = "p2"
    eng.state.battlefield.append(victim)
    card = _card("Lacerate Flesh", "Sorcery", "Lacerate Flesh deals 4 damage to target creature. Create a number of "
                 "Blood tokens equal to the amount of excess damage dealt to that creature this way.", is_sorcery=True)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, result.specs)
    p1 = eng.state.players[0]
    p1.hand.append(obj)
    p1.mana_pool.add_many({"C": 1})
    eng.cast_spell(p1, obj, targets=[victim])
    eng.resolve_until_stable()
    blood = [o for o in eng.state.battlefield if o.card.name == "Blood"]
    assert len(blood) == 3  # 4 damage on 1 toughness: excess 3

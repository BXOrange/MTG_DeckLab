"""PAR-284 milestone 18: distinct-value amounts beyond the plain count (RULE 105.2, 202.2, 205.2a, 601.2i, 702).

Golden Ratio (different powers), First Family (colors among permanents and the spells cast this turn), Korvold (permanent
types in a graveyard; the card types of permanents sacrificed this turn), Odric (listed abilities among creatures),
Niv-Mizzet, Guildpact (two-colored pairs), General Tazri ("those creatures") and Kianne (exiled with study counters).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import attach_to_object
from mtg_analyzer.game.continuous import count_selector
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.count_phrase import parse_amount_phrase
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import AbilitySpec, SpecValidationError
from tests.test_par284_this_way_windows import _card, _engine


def _put(eng, name, type_line="Creature — Bear", cost="{1}", power=1, **kw):
    card = Card(id=name, name=name, type_line=type_line, mana_cost_string=cost, converted_mana_cost=1,
                oracle_text="", is_creature="Creature" in type_line, power=power if "Creature" in type_line else None,
                toughness=power if "Creature" in type_line else None, **kw)
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    eng.state.battlefield.append(obj)
    return obj


def _count(eng, phrase):
    selector = parse_amount_phrase(phrase)
    assert selector is not None, phrase
    eng.recompute_continuous_effects()
    return count_selector(eng.state, "p1", selector)


def test_different_powers_count_each_value_once():
    eng = _engine()
    for name, power in (("A", 1), ("B", 1), ("C", 3)):
        _put(eng, name, power=power)
    assert _count(eng, "the number of different powers among creatures you control") == 2


def test_golden_ratio_draws_one_per_different_power():
    result = parse_oracle(_card("Golden Ratio", "Sorcery", "Draw a card for each different power among creatures you control.",
                               is_sorcery=True))
    assert result.modeled, result.unclaimed
    eng = _engine()
    p1 = eng.state.players[0]
    for i in range(5):
        p1.library.append(GameObject(_card(f"L{i}", "Instant"), owner_id="p1", zone=Zone.LIBRARY))
    for name, power in (("A", 1), ("B", 1), ("C", 3)):
        _put(eng, name, power=power)
    card = _card("Golden Ratio", "Sorcery", "Draw a card for each different power among creatures you control.", is_sorcery=True)
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, result.specs)
    p1.hand.append(obj)
    p1.mana_pool.add_many({"C": 1})
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()
    assert len(p1.hand) == 2


def test_colors_among_permanents_and_spells_cast_this_turn():
    eng = _engine()
    _put(eng, "Green Bear", cost="{G}")
    phrase = "the number of colors among permanents you control and spells you've cast this turn"
    assert _count(eng, phrase) == 1  # no spell cast yet
    eng.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p1", colors=["U", "G"], object_types=["instant"]))
    assert _count(eng, phrase) == 2  # green is shared, blue is new
    eng.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p2", colors=["R"], object_types=["instant"]))
    assert _count(eng, phrase) == 2  # an opponent's spell is not "you've cast"


def test_permanent_types_among_cards_in_a_graveyard_exclude_instants():
    eng = _engine()
    p1 = eng.state.players[0]
    for name, line in (("Cr", "Artifact Creature — Golem"), ("Sp", "Instant"), ("En", "Enchantment")):
        p1.graveyard.append(GameObject(_card(name, line), owner_id="p1", zone=Zone.GRAVEYARD))
    assert _count(eng, "the number of permanent types among cards in your graveyard") == 3  # artifact, creature, enchantment


def test_card_types_among_permanents_sacrificed_this_turn():
    eng = _engine()
    selector = parse_amount_phrase("the number of card types among permanents you've sacrificed this turn")
    assert selector == "card_types_among_permanents_sacrificed_this_turn"
    for types in (["artifact", "creature"], ["creature"], ["land"]):
        eng.state.fire_event(GameEvent(EventType.SACRIFICE, player_id="p1", object_types=types))
    eng.state.fire_event(GameEvent(EventType.SACRIFICE, player_id="p2", object_types=["enchantment"]))
    assert count_selector(eng.state, "p1", selector) == 3


def test_korvold_costs_one_less_per_sacrificed_card_type():
    from mtg_analyzer.game.continuous import self_cost_reduction_for

    oracle = ("This spell costs {1} less to cast for each card type among permanents you've sacrificed this turn.\n"
              "Flying, trample, haste\nWhenever ~ deals combat damage to a player, put X +1/+1 counters on ~ and draw X "
              "cards, where X is the number of permanent types among cards in your graveyard.")
    card = _card("Korvold, Gleeful Glutton", "Legendary Creature — Dragon Noble", oracle, is_creature=True, power=4, toughness=4)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    eng = _engine()
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, result.specs)
    assert self_cost_reduction_for(obj, eng.state, "p1")[0] == 0
    for types in (["artifact", "creature"], ["creature"]):
        eng.state.fire_event(GameEvent(EventType.SACRIFICE, player_id="p1", object_types=types))
    assert self_cost_reduction_for(obj, eng.state, "p1")[0] == 2  # artifact and creature


def test_odric_counts_each_listed_ability_once():
    eng = _engine()
    flier = _put(eng, "Flier")
    flier.card.oracle_text = "Flying, trample"
    flier.card.keywords = ["Flying", "Trample"]
    other = _put(eng, "Other")
    other.card.keywords = ["Flying", "Vigilance"]
    _put(eng, "Plain")
    listed = ("flying, first strike, double strike, deathtouch, haste, hexproof, indestructible, lifelink, menace, "
              "reach, trample, and vigilance")
    assert _count(eng, f"the number of abilities from among {listed} found among creatures you control") == 3


def test_listed_abilities_outside_the_vocabulary_are_refused():
    base = {"zone": "battlefield", "of": "you", "distinct": "keyword"}
    AbilitySpec._validate_selector({**base, "keywords": ["flying", "trample"]})
    for bad in ({**base, "keywords": ["banding"]}, {**base}, {"zone": "battlefield", "of": "you", "keywords": ["flying"]},
                {"zone": "battlefield", "of": "you", "distinct": "power", "with_spells_cast_this_turn": True}):
        with pytest.raises(SpecValidationError):
            AbilitySpec._validate_selector(bad)


def test_color_pairs_count_only_two_colored_permanents():
    eng = _engine()
    _put(eng, "GU1", cost="{G}{U}")
    _put(eng, "UG2", cost="{U}{G}")  # the same pair
    _put(eng, "BR", cost="{B}{R}")
    _put(eng, "Mono", cost="{R}")
    _put(eng, "Three", cost="{W}{U}{B}")
    assert _count(eng, "the number of different color pairs among permanents you control that are exactly two colors") == 2


def test_tazri_pumps_by_the_colors_among_the_pumped_group():
    specs = parse_effect_body("ally creatures you control get +x/+x until end of turn, where x is the number of colors among those creatures.")
    assert specs is not None and [s.type for s in specs] == ["bind"]
    selector = specs[0].params["amount"]["selector"]
    assert selector["distinct"] == "color" and selector["filter"] == {"subtype": "ally", "card_type": "creature"}


def test_kianne_counts_mana_values_of_cards_exiled_with_study_counters():
    eng = _engine()
    p1 = eng.state.players[0]
    for name, mv, counters in (("S1", 2, {"study": 1}), ("S2", 2, {"study": 1}), ("S3", 5, {"study": 2}), ("Plain", 7, {})):
        obj = GameObject(_card(name, "Sorcery", mv=mv), owner_id="p1", zone=Zone.EXILE)
        obj.counters = dict(counters)
        p1.exile.append(obj)
    assert _count(eng, "the number of different mana values among nonland cards you own in exile with study counters on them") == 2


@pytest.mark.parametrize("name, type_line, oracle", [
    ("First Family", "Instant", "You draw X cards and gain X life, where X is the number of colors among permanents you control and spells you've cast this turn."),
    ("Odric, Blood-Cursed", "Legendary Creature — Vampire Soldier",
     "When ~ enters, create X Blood tokens, where X is the number of abilities from among flying, first strike, double strike, "
     "deathtouch, haste, hexproof, indestructible, lifelink, menace, reach, trample, and vigilance found among creatures you control."),
    ("Niv-Mizzet, Guildpact", "Legendary Creature — Dragon Avatar",
     "Whenever ~ deals combat damage to a player, it deals X damage to any target, target player draws X cards, and you gain X life, "
     "where X is the number of different color pairs among permanents you control that are exactly two colors."),
    ("General Tazri", "Legendary Creature — Human Ally",
     "{W}{U}{B}{R}{G}: Ally creatures you control get +X/+X until end of turn, where X is the number of colors among those creatures."),
])
def test_real_cards_are_modeled(name, type_line, oracle):
    result = parse_oracle(_card(name, type_line, oracle, is_creature="Creature" in type_line, is_instant=type_line == "Instant",
                                **({"power": 2, "toughness": 2} if "Creature" in type_line else {})))
    assert result.modeled, (name, result.unclaimed)

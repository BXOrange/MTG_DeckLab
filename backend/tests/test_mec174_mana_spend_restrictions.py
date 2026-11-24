"""MEC-174 (RULE 605.3a): the wider "Spend this mana only ..." vocabulary, enforced where the mana is spent.

Each shape is read by `parser/oracle/mana_riders.parse_restriction` off the real printed text, carried by the
`ManaAbility` the engine builds, and checked on a real `GameEngine`: restricted mana pays what the clause names and
nothing else (a disallowed spell or ability is refused, restricted mana never covers another spell's generic cost).
"""
import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.costs import parse_activation_cost
from mtg_analyzer.game.effects.core import ActivatedAbility, DrawCardEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.mana_abilities import (
    parse_mana_abilities,
    restriction_predicate_for_activation,
    restriction_predicate_for_cast,
)
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.parser.oracle.mana_riders import is_executed_rider, parse_restriction
from mtg_analyzer.services.card_database import CardDatabase

_DB = CardDatabase(DB_PATH)


def _real(name):
    card = _DB.get_card(name)
    if card is None:
        pytest.skip(f"{name} is not in the card cache")
    return card


def _restricted_ability(name):
    return next(a for a in parse_mana_abilities(_real(name)) if a.restriction is not None)


def _spell(name, type_line, cost="{1}{G}", **flags):
    return Card(id=name, name=name, type_line=type_line, mana_cost_string=cost,
                converted_mana_cost=ManaCost.parse(cost).converted_mana_cost, **flags)


def _engine(hand_cards=()):
    eng = GameEngine.new_game([("p1", "Alice", list(hand_cards))], starting_life=20, starting_hand=len(hand_cards))
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng, eng.state.active_player


def _in_hand(player, name):
    return next(obj for obj in player.hand if obj.name == name)


def _on_battlefield(eng, card):
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    return obj


def _draw_ability(eng, player, source, cost="{2}"):
    ability = ActivatedAbility(
        effects=[DrawCardEffect(1, player=player)], cost=parse_activation_cost(f"{cost}: Draw a card."), source=source,
    )
    source.activated_abilities.append(ability)
    return ability


# --- parsing the real printed clauses ------------------------------------------------------------------------------


@pytest.mark.parametrize("name,expected", [
    ("Omen Hawker", {"kind": "ability_only", "allow_ability": True}),
    ("Sunken Citadel", {"kind": "ability_only", "allow_ability": True, "ability_types": ["land"]}),
    ("Soldevi Machinist", {"kind": "ability_only", "allow_ability": True, "ability_types": ["artifact"]}),
    ("Shang-Chi, Master of Kung Fu", {"kind": "ability_only", "allow_ability": True, "ability_types": ["creature"]}),
    ("Base Camp", {"kind": "type_list_spell", "types": ["cleric", "rogue", "warrior", "wizard"], "allow_ability": True,
                   "ability_types": ["cleric", "rogue", "warrior", "wizard"]}),
    ("Sage of the Unknowable", {"kind": "type_list_spell", "types": ["colorless"], "allow_ability": True}),
    ("Guidelight Optimizer", {"kind": "type_list_spell", "types": ["artifact"], "allow_ability": True}),
    ("Automated Artificer", {"kind": "type_list_spell", "types": ["artifact"], "allow_ability": True}),
    ("Gallifrey Council Chamber", {"kind": "type_list_spell", "types": ["time lord", "alien"], "allow_ability": True,
                                   "ability_types": ["time lord", "alien"]}),
    ("Woodland Weavemaster", {"kind": "type_list_spell", "types": ["elf"], "allow_ability": True,
                              "ability_types": ["elf"]}),
    ("Maelstrom of the Spirit Dragon", {"kind": "type_list_spell", "types": ["dragon", "omen"]}),
    ("Master of Dark Rites", {"kind": "type_list_spell", "types": ["vampire", "cleric", "demon"]}),
    ("Séance Board", {"kind": "type_list_spell", "types": ["instant", "sorcery", "demon", "spirit"]}),
    ("Cormela, Glamour Thief", {"kind": "type_list_spell", "types": ["instant", "sorcery"]}),
    ("Lord of the Forsaken", {"kind": "spell_from_zone", "zone": "graveyard", "owned_by_you": True}),
    ("Interdimensional Web Watch", {"kind": "spell_from_zone", "zone": "exile"}),
    ("Mm'menon, the Right Hand", {"kind": "spell_from_zone", "not_zone": "hand"}),
    ("Klauth, Unrivaled Ancient", {"kind": "spell"}),
    ("Anina, Natural Parallelist", {"kind": "x_spell"}),
])
def test_real_card_restriction_is_read_and_carried_by_the_mana_ability(name, expected):
    card = _real(name)
    restrictions = [a.restriction for a in parse_mana_abilities(card) if a.restriction is not None]
    if not restrictions:
        # Klauth's mana is a trigger's Add clause, not a cost-line ability: read the sentence itself.
        text = next(s for s in card.oracle_text.split("\n") if "Spend this mana only" in s)
        assert parse_restriction(text) == expected
        return
    assert restrictions == [expected]


@pytest.mark.parametrize("sentence", [
    "Spend this mana only to cast an instant or sorcery spell or to gain a Class level.",   # a level is no spell/ability
    "Spend this mana only to cast an elemental spell or a chandra planeswalker spell.",     # a compound, not a type word
    "Spend this mana only to cast a creature spell or activate an ability of a frobnitz.",  # an unknown source type
    "Spend this mana only to cast an equipment spell or activate an equip ability.",        # equip is not a source type
    "Spend this mana only to cast spells from your hand or graveyard.",
])
def test_shapes_outside_the_vocabulary_stay_unclaimed(sentence):
    assert parse_restriction(sentence) is None
    assert not is_executed_rider(sentence)


# --- enforcement at payment ----------------------------------------------------------------------------------------


def test_omen_hawker_mana_pays_only_for_abilities():
    bear_spell = _spell("Bear", "Creature — Bear", "{C}{U}", is_creature=True)
    eng, p1 = _engine([bear_spell])
    hawker = _on_battlefield(eng, _real("Omen Hawker"))
    eng.tap_for_mana(p1, hawker)
    assert p1.mana_pool.total() == 2 and p1.mana_pool.pool["U"] == 0  # tagged, not free-floating
    # Not a spell of any kind, not even a generic cost of one.
    assert not eng.can_cast(p1, _in_hand(p1, "Bear"))
    # An ability of any source: {2} fully paid by the two restricted mana.
    machine = _on_battlefield(eng, _spell("Machine", "Artifact", "{1}"))
    ability = _draw_ability(eng, p1, machine)
    assert eng.can_activate(p1, machine, ability)
    eng.activate_ability(p1, machine)
    assert p1.mana_pool.total() == 0


def test_restricted_mana_partially_pays_an_ability_and_the_rest_comes_from_the_pool():
    eng, p1 = _engine()
    hawker = _on_battlefield(eng, _real("Omen Hawker"))
    eng.tap_for_mana(p1, hawker)
    machine = _on_battlefield(eng, _spell("Machine", "Artifact", "{1}"))
    ability = _draw_ability(eng, p1, machine, "{3}")
    assert not eng.can_activate(p1, machine, ability)  # 2 restricted mana, nothing else
    p1.mana_pool.add_many({"G": 1})
    assert eng.can_activate(p1, machine, ability)
    eng.activate_ability(p1, machine)
    assert p1.mana_pool.total() == 0


def test_sunken_citadel_mana_pays_a_land_sources_ability_but_not_a_creatures():
    eng, p1 = _engine()
    p1.mana_pool.add_many({"C": 0})
    citadel = _real("Sunken Citadel")
    citadel_obj = _on_battlefield(eng, citadel)
    citadel_obj.chosen_color = "G"
    abilities = parse_mana_abilities(citadel)
    index = next(i for i, a in enumerate(abilities) if a.restriction is not None)
    eng.tap_for_mana(p1, citadel_obj, ability_index=index)
    assert p1.mana_pool.total() == 2
    land = _on_battlefield(eng, Card(id="Cave", name="Cave", type_line="Land", is_land=True))
    land_ability = _draw_ability(eng, p1, land)
    creature = _on_battlefield(eng, _spell("Bear", "Creature — Bear", "{1}", is_creature=True))
    creature_ability = _draw_ability(eng, p1, creature)
    assert not eng.can_activate(p1, creature, creature_ability)
    assert eng.can_activate(p1, land, land_ability)
    eng.activate_ability(p1, land)
    assert p1.mana_pool.total() == 0


def test_base_camp_mana_casts_a_cleric_and_pays_a_cleric_sources_ability_only():
    cleric = _spell("Acolyte", "Creature — Human Cleric", "{1}{W}", is_creature=True)
    bear = _spell("Bear", "Creature — Bear", "{1}{W}", is_creature=True)
    eng, p1 = _engine([cleric, bear])
    base_camp = _real("Base Camp")
    obj = _on_battlefield(eng, base_camp)
    index = next(i for i, a in enumerate(parse_mana_abilities(base_camp)) if a.restriction is not None)
    # Two taps' worth of restricted mana: one cast, one ability.
    eng.tap_for_mana(p1, obj, ability_index=index)
    assert p1.mana_pool.total() == 1
    acolyte, grizzly = _in_hand(p1, "Acolyte"), _in_hand(p1, "Bear")
    p1.mana_pool.add_many({"W": 1})  # unrestricted top-up so the {1}{W} is affordable
    assert eng.can_cast(p1, acolyte)
    assert not eng.can_cast(p1, grizzly)  # the restricted mana is no good for a non-Cleric, nor its generic part
    eng.cast_spell(p1, acolyte)
    assert p1.mana_pool.total() == 0

    obj.tapped = False
    eng.tap_for_mana(p1, obj, ability_index=index)
    wizard = _on_battlefield(eng, _spell("Wiz", "Creature — Human Wizard", "{1}", is_creature=True))
    wizard_ability = _draw_ability(eng, p1, wizard, "{1}")
    other = _on_battlefield(eng, _spell("Golem", "Artifact Creature — Golem", "{1}", is_creature=True))
    other_ability = _draw_ability(eng, p1, other, "{1}")
    assert not eng.can_activate(p1, other, other_ability)
    assert eng.can_activate(p1, wizard, wizard_ability)


def test_sage_of_the_unknowable_mana_casts_a_colorless_spell_or_pays_any_ability():
    colorless = _spell("Wastes Golem", "Artifact Creature — Golem", "{1}", is_creature=True)
    colored = _spell("Bear", "Creature — Bear", "{1}{G}", is_creature=True)
    eng, p1 = _engine([colorless, colored])
    sage = _on_battlefield(eng, _real("Sage of the Unknowable"))
    eng.tap_for_mana(p1, sage)
    golem, bear = (_in_hand(p1, "Wastes Golem"), _in_hand(p1, "Bear"))
    assert eng.can_cast(p1, golem)  # only the restricted {C} is in the pool
    machine = _on_battlefield(eng, _spell("Machine", "Artifact", "{1}"))
    ability = _draw_ability(eng, p1, machine, "{1}")
    assert eng.can_activate(p1, machine, ability)  # any ability, still only the restricted {C}
    p1.mana_pool.add_many({"G": 1})  # the colored pip is payable; only the restricted {C} is in question
    assert not eng.can_cast(p1, bear)


def test_klauth_style_any_spell_mana_pays_spells_but_no_ability():
    eng, p1 = _engine([_spell("Bolt", "Instant", "{R}", is_instant=True)])
    p1.mana_pool.add("R", 1, restriction={"kind": "spell"})
    assert eng.can_cast(p1, _in_hand(p1, "Bolt"))
    machine = _on_battlefield(eng, _spell("Machine", "Artifact", "{1}"))
    ability = _draw_ability(eng, p1, machine, "{1}")
    assert not eng.can_activate(p1, machine, ability)


# --- predicate-level checks for the zone / X shapes ----------------------------------------------------------------


def _obj(zone, type_line="Creature — Bear", owner="p1", **flags):
    return GameObject(Card(id="o", name="o", type_line=type_line, **flags), owner_id=owner, zone=zone)


def test_graveyard_restriction_reads_the_zone_the_card_is_cast_from_and_its_owner():
    restriction = {"kind": "spell_from_zone", "zone": "graveyard", "owned_by_you": True, "owner_id": "p1"}
    assert restriction_predicate_for_cast(_obj(Zone.GRAVEYARD))(restriction)
    assert not restriction_predicate_for_cast(_obj(Zone.HAND))(restriction)
    assert not restriction_predicate_for_cast(_obj(Zone.EXILE))(restriction)
    assert not restriction_predicate_for_cast(_obj(Zone.GRAVEYARD, owner="p2"))(restriction)  # "your" graveyard
    assert not restriction_predicate_for_activation(_obj(Zone.BATTLEFIELD))(restriction)


def test_not_from_hand_restriction_refuses_only_the_hand():
    restriction = {"kind": "spell_from_zone", "not_zone": "hand"}
    assert not restriction_predicate_for_cast(_obj(Zone.HAND))(restriction)
    assert restriction_predicate_for_cast(_obj(Zone.EXILE))(restriction)
    assert restriction_predicate_for_cast(_obj(Zone.COMMAND))(restriction)


def test_tapping_binds_a_your_graveyard_restriction_to_the_player_that_produced_the_mana():
    eng, p1 = _engine()
    creeper = _on_battlefield(eng, _real("Rootcoil Creeper"))
    eng.tap_for_mana(p1, creeper, ability_index=1)
    [lot] = p1.mana_pool.restricted
    assert lot["restriction"]["owner_id"] == "p1"


def test_x_spell_restriction_needs_an_x_in_the_cost_and_never_pays_an_ability():
    restriction = {"kind": "x_spell"}
    obj = _obj(Zone.HAND, "Sorcery", is_sorcery=True)
    assert restriction_predicate_for_cast(obj, has_x=True)(restriction)
    assert not restriction_predicate_for_cast(obj, has_x=False)(restriction)
    assert not restriction_predicate_for_activation(obj, has_x=True)(restriction)


def test_type_list_spell_matches_card_types_and_subtypes_alike():
    restriction = {"kind": "type_list_spell", "types": ["aura", "equipment"]}
    aura = _obj(Zone.HAND, "Enchantment — Aura")
    equipment = _obj(Zone.HAND, "Artifact — Equipment")
    creature = _obj(Zone.HAND, "Creature — Bear", is_creature=True)
    assert restriction_predicate_for_cast(aura)(restriction)
    assert restriction_predicate_for_cast(equipment)(restriction)
    assert not restriction_predicate_for_cast(creature)(restriction)
    card_types = {"kind": "type_list_spell", "types": ["instant", "sorcery"]}
    assert restriction_predicate_for_cast(_obj(Zone.HAND, "Instant", is_instant=True))(card_types)
    assert not restriction_predicate_for_cast(creature)(card_types)

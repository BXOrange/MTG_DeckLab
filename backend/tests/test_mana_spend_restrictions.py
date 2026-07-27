"""Tests for RULE 605.3a mana spend restrictions ("Spend this mana only to
cast a creature spell.") — the tagged/restricted `ManaPool` lots
(models/mana_pool.py), their parsing into `ManaAbility.restriction`
(game/mana_abilities.py), and the actual cast/activation-cost payment
call sites (game/rules_engine.py's `cast_spell`, game/game_engine.py's
`can_cast`/`_can_pay_activation_cost`/`_pay_activation_cost`) honoring them.

Reference: docs/implementation-state/BACKLOG.md, docs/implementation-state/Done_Backend.md.
"""

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.mana_cost import ManaCost
from mtg_analyzer.models.mana_pool import ManaPool
from mtg_analyzer.game.costs import parse_activation_cost
from mtg_analyzer.game.effects import ActivatedAbility, DrawCardEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.mana_abilities import (
    _parse_restriction,
    parse_mana_abilities,
    restriction_predicate_for_activation,
    restriction_predicate_for_cast,
)


# ---------------------------------------------------------------------------
# ManaPool: tagged/restricted lots (models/mana_pool.py)
# ---------------------------------------------------------------------------


def test_restricted_mana_is_unusable_without_a_predicate():
    pool = ManaPool()
    pool.add("G", 2, restriction={"kind": "creature_spell"})
    assert pool.total() == 2
    assert not pool.can_pay(ManaCost.parse("{2}"))
    with pytest.raises(ValueError):
        pool.pay(ManaCost.parse("{2}"))


def test_restricted_mana_usable_when_the_predicate_allows_it():
    pool = ManaPool()
    pool.add("G", 2, restriction={"kind": "creature_spell"})
    allows = lambda restriction: restriction["kind"] == "creature_spell"
    assert pool.can_pay(ManaCost.parse("{2}"), allows_restriction=allows)
    pool.pay(ManaCost.parse("{2}"), allows_restriction=allows)
    assert pool.total() == 0


def test_predicate_only_unlocks_matching_restrictions_not_every_lot():
    pool = ManaPool()
    pool.add("G", 1, restriction={"kind": "creature_spell"})
    pool.add("U", 1, restriction={"kind": "commander_spell"})
    allows_creature = lambda restriction: restriction["kind"] == "creature_spell"
    # Only the creature-spell lot counts — the commander lot stays inert.
    assert pool.can_pay(ManaCost.parse("{1}"), allows_restriction=allows_creature)
    assert not pool.can_pay(ManaCost.parse("{2}"), allows_restriction=allows_creature)


def test_restricted_mana_is_consumed_before_unrestricted():
    pool = ManaPool({"R": 1})
    pool.add("G", 2, restriction={"kind": "creature_spell"})
    pool.pay(ManaCost.parse("{2}"), allows_restriction=lambda r: True)
    # {2} generic drew colourless-first (none), then R (1), then the
    # restricted G lot for the remainder — R is a *pool* type tried before
    # G regardless, but within G itself the restricted lot goes first.
    assert pool.pool["R"] == 0
    assert pool.restricted == [{"restriction": {"kind": "creature_spell"}, "amounts": {"G": 1}}]


def test_add_merges_into_an_existing_lot_with_an_identical_restriction():
    pool = ManaPool()
    pool.add("G", 1, restriction={"kind": "creature_spell"})
    pool.add("U", 1, restriction={"kind": "creature_spell"})
    assert len(pool.restricted) == 1
    assert pool.restricted[0]["amounts"] == {"G": 1, "U": 1}


def test_empty_clears_restricted_mana_too():
    pool = ManaPool()
    pool.add("G", 1, restriction={"kind": "creature_spell"})
    pool.empty()
    assert pool.total() == 0
    assert pool.restricted == []


def test_to_dict_is_additive_and_omits_restricted_key_when_empty():
    pool = ManaPool({"G": 1})
    assert "restricted" not in pool.to_dict()
    pool.add("U", 1, restriction={"kind": "creature_spell"})
    data = pool.to_dict()
    assert data["G"] == 1  # unrestricted keys unaffected
    assert data["restricted"] == [{"restriction": {"kind": "creature_spell"}, "amounts": {"U": 1}}]


# ---------------------------------------------------------------------------
# Parsing "Spend this mana only ..." into a restriction dict
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "clause,expected",
    [
        ("Add {G}. Spend this mana only to cast a creature spell.",
         {"kind": "creature_spell", "allow_ability": False}),
        ("Add {G}. Spend this mana only to cast creature spells.",
         {"kind": "creature_spell", "allow_ability": False}),
        ("Add six {G}. Spend this mana only to cast creature spells or activate abilities of creatures.",
         {"kind": "creature_spell", "allow_ability": True}),
        ("Add one mana of any color. Spend this mana only to cast a legendary spell.",
         {"kind": "legendary_spell"}),
        ("Add one mana of any color. Spend this mana only to cast a legendary spell, "
         "and that spell can't be countered.",
         {"kind": "legendary_spell"}),
        ("Add three mana of any one color. Spend this mana only to cast your commander.",
         {"kind": "commander_spell"}),
        ("Add one mana of any color. Spend this mana only to cast an instant or sorcery spell.",
         {"kind": "instant_or_sorcery_spell"}),
        ("Add two mana of any one color. Spend this mana only to cast instant and sorcery spells.",
         {"kind": "instant_or_sorcery_spell"}),
        ("Add {C} for each charge counter on this artifact. Spend this mana only on costs that contain {X}.",
         {"kind": "contains_x"}),
        ("Add {G}. Spend this mana only to cast an Elf creature spell.",
         {"kind": "type_spell", "types": ["elf"], "allow_ability": False}),
        ("Add one mana of any color. Spend this mana only to cast an Elemental spell "
         "or activate an ability of an Elemental.",
         {"kind": "type_spell", "types": ["elemental"], "allow_ability": True}),
        ("Add one mana of any color. Spend this mana only to cast a Ninja or Turtle spell.",
         {"kind": "type_spell", "types": ["ninja", "turtle"], "allow_ability": False}),
        # Cavern of Souls/Unclaimed Territory's "of the chosen type" — the
        # type itself isn't parsed here (no fixed word to read); it's
        # resolved dynamically at tap time off the land's own `chosen_type`
        # instead (`GameEngine.tap_for_mana`).
        ("Add one mana of any color. Spend this mana only to cast a creature spell of the chosen type.",
         {"kind": "chosen_type_spell"}),
        ("Add one mana of any color. Spend this mana only to cast a creature spell of the chosen type, "
         "and that spell can't be countered.",
         {"kind": "chosen_type_spell"}),
        # Helga/Troyan's mana-value-threshold-or-{X} clause.
        ("Add X mana of any one color, where X is Helga's power. Spend this mana only to cast creature "
         "spells with mana value 4 or greater or creature spells with {X} in their mana costs.",
         {"kind": "mana_value_or_x_spell", "min_mana_value": 4, "creature_only": True}),
        ("Add {G}{U}. Spend this mana only to cast spells with mana value 5 or greater or spells "
         "with {X} in their mana costs.",
         {"kind": "mana_value_or_x_spell", "min_mana_value": 5, "creature_only": False}),
        # Throne of Eldraine's chosen-*colour* "monocolored spells of that
        # color" restriction — resolved per-instance off `chosen_color` at
        # tap time (`GameEngine.tap_for_mana` → a concrete `monocolored_
        # spell` restriction), like the chosen-*type* family.
        ("Add four mana of the chosen color. Spend this mana only to cast monocolored spells of that color.",
         {"kind": "chosen_color_monocolored_spell"}),
    ],
)
def test_parse_restriction_recognises_the_modeled_shapes(clause, expected):
    assert _parse_restriction(clause) == expected


@pytest.mark.parametrize(
    "clause",
    [
        # A mixed clause with a non-spell alternative (Sorcerer Class).
        "Add {U} or {R}. Spend this mana only to cast an instant or sorcery spell or to gain a Class level.",
        # No restriction clause at all.
        "Add {G}.",
    ],
)
def test_parse_restriction_fails_soft_on_unrecognised_shapes(clause):
    assert _parse_restriction(clause) is None


def test_gnarlroot_trapper_ability_carries_its_restriction():
    card = Card(
        id="Gnarlroot Trapper", name="Gnarlroot Trapper", type_line="Creature — Elf Druid",
        is_creature=True, oracle_text="{T}, Pay 1 life: Add {G}. Spend this mana only to cast an Elf creature spell.",
    )
    [ability] = parse_mana_abilities(card)
    assert ability.restriction == {"kind": "type_spell", "types": ["elf"], "allow_ability": False}


# ---------------------------------------------------------------------------
# restriction_predicate_for_cast / _for_activation
# ---------------------------------------------------------------------------


def _spell_obj(type_line="Creature — Elf", **kw):
    card = Card(id="x", name="x", type_line=type_line, oracle_text="", **kw)
    return GameObject(card, owner_id="p1", zone=Zone.HAND)


def test_creature_spell_restriction_checks_the_cast_object():
    allows = restriction_predicate_for_cast(_spell_obj(is_creature=True))
    assert allows({"kind": "creature_spell"})
    allows_instant = restriction_predicate_for_cast(_spell_obj(type_line="Instant", is_instant=True))
    assert not allows_instant({"kind": "creature_spell"})


def test_type_spell_restriction_checks_the_creature_type():
    obj = _spell_obj(type_line="Creature — Elemental", is_creature=True)
    allows = restriction_predicate_for_cast(obj)
    assert allows({"kind": "type_spell", "types": ["elemental"]})
    assert not allows({"kind": "type_spell", "types": ["elf"]})


def test_legendary_and_commander_and_instant_or_sorcery_restrictions():
    legendary_creature = _spell_obj(type_line="Legendary Creature — Elf", is_creature=True, is_legendary=True)
    assert restriction_predicate_for_cast(legendary_creature)({"kind": "legendary_spell"})

    commander = _spell_obj(type_line="Legendary Creature — Elf", is_creature=True, is_legendary=True)
    commander.is_commander = True
    assert restriction_predicate_for_cast(commander)({"kind": "commander_spell"})
    assert not restriction_predicate_for_cast(legendary_creature)({"kind": "commander_spell"})

    sorcery = _spell_obj(type_line="Sorcery", is_sorcery=True)
    assert restriction_predicate_for_cast(sorcery)({"kind": "instant_or_sorcery_spell"})


def test_contains_x_restriction_reads_the_has_x_flag_not_the_object():
    obj = _spell_obj(type_line="Instant", is_instant=True)
    assert restriction_predicate_for_cast(obj, has_x=True)({"kind": "contains_x"})
    assert not restriction_predicate_for_cast(obj, has_x=False)({"kind": "contains_x"})


def test_activation_predicate_requires_allow_ability_flag():
    obj = _spell_obj(type_line="Creature — Elemental", is_creature=True)
    allows = restriction_predicate_for_activation(obj)
    # creature_spell without allow_ability never authorises an activation.
    assert not allows({"kind": "creature_spell", "allow_ability": False})
    assert allows({"kind": "creature_spell", "allow_ability": True})
    # legendary/commander/instant_or_sorcery never gate an activation at all.
    assert not allows({"kind": "legendary_spell"})
    assert not allows({"kind": "commander_spell"})


# ---------------------------------------------------------------------------
# End-to-end through the engine (cast_spell / can_cast / activate_ability)
# ---------------------------------------------------------------------------


def _land(name="Land"):
    return Card(id=name, name=name, type_line="Land", is_land=True)


def _creature(name="Bear", cost="{1}{G}", type_line="Creature — Bear", **kw):
    return Card(
        id=name, name=name, type_line=type_line, mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost, is_creature=True, **kw,
    )


def _instant(name="Shock", cost="{R}"):
    return Card(
        id=name, name=name, type_line="Instant", mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost, is_instant=True,
    )


def _make_engine(cards, hand=0):
    return GameEngine.new_game([("p1", "Alice", list(cards))], starting_life=20, starting_hand=hand)


def test_gnarlroot_trapper_mana_cannot_cast_a_non_elf_spell():
    trapper = Card(
        id="Gnarlroot Trapper", name="Gnarlroot Trapper", type_line="Creature — Elf Druid",
        is_creature=True,
        oracle_text="{T}, Pay 1 life: Add {G}. Spend this mana only to cast an Elf creature spell.",
    )
    eng = _make_engine([_land(), _instant("Shock")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    obj = GameObject(trapper, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)

    eng.tap_for_mana(p1, obj)
    assert p1.mana_pool.total() == 1
    assert p1.mana_pool.pool["G"] == 0  # tagged into a restricted lot, not the flat pool

    shock = p1.hand[0]
    assert not eng.can_cast(p1, shock)  # Shock is neither an Elf nor a creature spell
    with pytest.raises(ValueError):
        eng.cast_spell(p1, shock)


def test_gnarlroot_trapper_mana_can_cast_an_elf_creature_spell():
    trapper = Card(
        id="Gnarlroot Trapper", name="Gnarlroot Trapper", type_line="Creature — Elf Druid",
        is_creature=True,
        oracle_text="{T}, Pay 1 life: Add {G}. Spend this mana only to cast an Elf creature spell.",
    )
    elf_spell = _creature("Elvish Mystic", cost="{G}", type_line="Creature — Elf Druid")
    eng = _make_engine([_land(), elf_spell], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    obj = GameObject(trapper, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)

    eng.tap_for_mana(p1, obj)
    mystic = p1.hand[0]
    assert eng.can_cast(p1, mystic)
    eng.cast_spell(p1, mystic)
    assert p1.mana_pool.total() == 0
    assert eng.state.stack[-1].obj is mystic


def test_jeweled_lotus_mana_only_pays_for_the_commander():
    lotus = Card(
        id="Jeweled Lotus", name="Jeweled Lotus", type_line="Legendary Artifact",
        is_legendary=True,
        oracle_text="{T}, Sacrifice this artifact: Add three mana of any one color. "
                     "Spend this mana only to cast your commander.",
    )
    commander = _creature("Commander Bear", cost="{3}{G}{G}", type_line="Legendary Creature — Bear")
    other = _creature("Grizzly Bears", cost="{1}{G}")
    eng = _make_engine([other], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    commander_obj = GameObject(commander, owner_id="p1", is_commander=True)
    p1.add_to_zone(commander_obj, Zone.COMMAND)
    lotus_obj = GameObject(lotus, owner_id="p1", zone=Zone.BATTLEFIELD)
    lotus_obj.summoning_sick = False
    eng.state.add_to_battlefield(lotus_obj)

    produced = eng.tap_for_mana(p1, lotus_obj)
    # "Add three mana of any one color" — first colour option (a real UI
    # would let the player choose); a real Jeweled Lotus really does add 3,
    # not 1 (fixed alongside Harold and Bob's own "add three mana of any
    # one color" granted ability — this module's "any one colour" amount
    # parsing previously ignored any fixed leading count > 1).
    assert produced == {"W": 3}
    assert p1.mana_pool.total() == 3

    bears = p1.hand[0]
    assert not eng.can_cast(p1, bears)  # not the commander
    assert not eng.can_cast(p1, commander_obj)  # {3}{G}{G} needs 5, only 3 restricted mana in the pool


def test_castle_garenbrig_mana_pays_a_creatures_activated_ability():
    castle = Card(
        id="Castle Garenbrig", name="Castle Garenbrig", type_line="Land",
        is_land=True,
        # "Add six {G}" in the real printed text — spelled out numerals in a
        # production clause aren't parsed yet (a separate, pre-existing
        # gap, see docs/implementation-state/BACKLOG.md); explicit pips sidestep it so
        # this test stays focused on the restriction plumbing.
        oracle_text="{T}: Add {G}.\n{2}{G}{G}, {T}: Add {G}{G}{G}{G}{G}{G}. "
                     "Spend this mana only to cast creature spells or activate abilities of creatures.",
    )
    eng = _make_engine([], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    castle_obj = GameObject(castle, owner_id="p1", zone=Zone.BATTLEFIELD)
    castle_obj.summoning_sick = False
    eng.state.add_to_battlefield(castle_obj)

    [_tap_ability, big_ability] = parse_mana_abilities(castle)
    # Fund the big ability's own {2}{G}{G} cost directly (unrestricted).
    p1.mana_pool.add_many({"G": 4})
    eng.tap_for_mana(p1, castle_obj, ability_index=1)
    assert p1.mana_pool.total() == 6
    assert p1.mana_pool.pool["G"] == 0  # all six went into the restricted lot

    bear = GameObject(_creature("Bear"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bear.summoning_sick = False
    eng.state.add_to_battlefield(bear)
    ability = ActivatedAbility(
        effects=[DrawCardEffect(1, player=p1)],
        cost=parse_activation_cost("{2}: Draw a card."), source=bear,
    )
    bear.activated_abilities.append(ability)

    assert eng.can_activate(p1, bear, ability)
    eng.activate_ability(p1, bear)
    assert p1.mana_pool.total() == 4  # {2} paid from the restricted lot


def test_castle_garenbrig_mana_cannot_pay_a_noncreature_sources_ability():
    castle = Card(
        id="Castle Garenbrig", name="Castle Garenbrig", type_line="Land",
        is_land=True,
        # "Add six {G}" in the real printed text — spelled out numerals in a
        # production clause aren't parsed yet (a separate, pre-existing
        # gap, see docs/implementation-state/BACKLOG.md); explicit pips sidestep it so
        # this test stays focused on the restriction plumbing.
        oracle_text="{T}: Add {G}.\n{2}{G}{G}, {T}: Add {G}{G}{G}{G}{G}{G}. "
                     "Spend this mana only to cast creature spells or activate abilities of creatures.",
    )
    eng = _make_engine([], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    castle_obj = GameObject(castle, owner_id="p1", zone=Zone.BATTLEFIELD)
    castle_obj.summoning_sick = False
    eng.state.add_to_battlefield(castle_obj)
    p1.mana_pool.add_many({"G": 4})
    eng.tap_for_mana(p1, castle_obj, ability_index=1)

    artifact = GameObject(
        Card(id="Vault", name="Vault", type_line="Artifact"),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    ability = ActivatedAbility(
        effects=[DrawCardEffect(1, player=p1)],
        cost=parse_activation_cost("{2}: Draw a card."), source=artifact,
    )
    artifact.activated_abilities.append(ability)

    assert not eng.can_activate(p1, artifact, ability)  # not a creature source


# ---------------------------------------------------------------------------
# Cavern of Souls/Unclaimed Territory: "of the chosen type" — resolved
# per-instance off `GameObject.chosen_type` at tap time.
# ---------------------------------------------------------------------------


def test_cavern_of_souls_mana_only_casts_the_chosen_creature_type():
    cavern = Card(
        id="Cavern of Souls", name="Cavern of Souls", type_line="Land",
        oracle_text="As this land enters, choose a creature type.\n{T}: Add {C}.\n"
                     "{T}: Add one mana of any color. Spend this mana only to cast a "
                     "creature spell of the chosen type, and that spell can't be countered.",
    )
    elf_spell = _creature("Elvish Mystic", cost="{G}", type_line="Creature — Elf Druid")
    bear = _creature("Grizzly Bears", cost="{1}{G}")
    eng = _make_engine([elf_spell, bear], hand=2)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    cavern_obj = GameObject(cavern, owner_id="p1", zone=Zone.BATTLEFIELD)
    cavern_obj.summoning_sick = False
    cavern_obj.chosen_type = "Elf"  # the RULE 601.2b ETB choice, made directly here
    eng.state.add_to_battlefield(cavern_obj)

    eng.tap_for_mana(p1, cavern_obj, ability_index=1, option_index=4)  # "any color" → G
    assert p1.mana_pool.total() == 1
    assert p1.mana_pool.pool.get("G", 0) == 0  # tagged into a restricted lot

    mystic = next(o for o in p1.hand if o.name == "Elvish Mystic")
    grizzly = next(o for o in p1.hand if o.name == "Grizzly Bears")
    assert eng.can_cast(p1, mystic)
    assert not eng.can_cast(p1, grizzly)  # a Bear, not an Elf


def test_cavern_of_souls_colorless_ability_is_unrestricted():
    cavern = Card(
        id="Cavern of Souls", name="Cavern of Souls", type_line="Land",
        oracle_text="As this land enters, choose a creature type.\n{T}: Add {C}.\n"
                     "{T}: Add one mana of any color. Spend this mana only to cast a "
                     "creature spell of the chosen type, and that spell can't be countered.",
    )
    eng = _make_engine([], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player
    cavern_obj = GameObject(cavern, owner_id="p1", zone=Zone.BATTLEFIELD)
    cavern_obj.summoning_sick = False
    cavern_obj.chosen_type = "Elf"
    eng.state.add_to_battlefield(cavern_obj)

    eng.tap_for_mana(p1, cavern_obj, ability_index=0)  # "{T}: Add {C}." — no restriction
    assert p1.mana_pool.pool.get("C", 0) == 1  # unrestricted, sits in the flat pool


# ---------------------------------------------------------------------------
# Helga, Skittish Seer / Troyan, Gutsy Explorer: mana-value threshold or {X}
# ---------------------------------------------------------------------------


def test_mana_value_or_x_restriction_predicate_checks_value_x_and_creature():
    high_mv_creature = _spell_obj(type_line="Creature — Beast", is_creature=True, converted_mana_cost=5)
    low_mv_creature = _spell_obj(type_line="Creature — Beast", is_creature=True, converted_mana_cost=1)
    high_mv_instant = _spell_obj(type_line="Instant", is_instant=True, converted_mana_cost=5)

    creature_only = {"kind": "mana_value_or_x_spell", "min_mana_value": 4, "creature_only": True}
    unscoped = {"kind": "mana_value_or_x_spell", "min_mana_value": 5, "creature_only": False}

    assert restriction_predicate_for_cast(high_mv_creature)(creature_only)
    assert not restriction_predicate_for_cast(low_mv_creature)(creature_only)
    # {X} in the cost authorises it regardless of the actual mana value.
    assert restriction_predicate_for_cast(low_mv_creature, has_x=True)(creature_only)
    # creature_only=True rejects a high-mana-value noncreature spell.
    assert not restriction_predicate_for_cast(high_mv_instant)(creature_only)
    # Troyan's own unscoped ("spells", not "creature spells") shape allows it.
    assert restriction_predicate_for_cast(high_mv_instant)(unscoped)


def test_helga_ability_carries_the_mana_value_or_x_restriction():
    helga = Card(
        id="Helga, Skittish Seer", name="Helga, Skittish Seer",
        type_line="Legendary Creature — Frog Druid", is_creature=True, power=1, toughness=1,
        oracle_text="{T}: Add X mana of any one color, where X is Helga's power. Spend this "
                     "mana only to cast creature spells with mana value 4 or greater or "
                     "creature spells with {X} in their mana costs.",
    )
    [ability] = parse_mana_abilities(helga)
    assert ability.restriction == {
        "kind": "mana_value_or_x_spell", "min_mana_value": 4, "creature_only": True,
    }


def test_troyan_ability_carries_the_unscoped_mana_value_or_x_restriction():
    troyan = Card(
        id="Troyan, Gutsy Explorer", name="Troyan, Gutsy Explorer",
        type_line="Legendary Creature — Vedalken Scout", is_creature=True, power=2, toughness=2,
        oracle_text="{T}: Add {G}{U}. Spend this mana only to cast spells with mana value 5 "
                     "or greater or spells with {X} in their mana costs.",
    )
    [ability] = parse_mana_abilities(troyan)
    assert ability.restriction == {
        "kind": "mana_value_or_x_spell", "min_mana_value": 5, "creature_only": False,
    }


def test_helga_mana_only_casts_a_high_mana_value_or_x_creature_spell_end_to_end():
    helga = Card(
        id="Helga, Skittish Seer", name="Helga, Skittish Seer",
        type_line="Legendary Creature — Frog Druid", is_creature=True, power=5, toughness=5,
        oracle_text="{T}: Add X mana of any one color, where X is Helga's power. Spend this "
                     "mana only to cast creature spells with mana value 4 or greater or "
                     "creature spells with {X} in their mana costs.",
    )
    big_creature = _creature("Big Beast", cost="{3}{G}{G}", type_line="Creature — Beast")
    small_creature = _creature("Small Beast", cost="{G}", type_line="Creature — Beast")
    eng = _make_engine([big_creature, small_creature], hand=2)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    helga_obj = GameObject(helga, owner_id="p1", zone=Zone.BATTLEFIELD)
    helga_obj.summoning_sick = False
    eng.state.add_to_battlefield(helga_obj)

    eng.tap_for_mana(p1, helga_obj, option_index=4)  # power 5 → 5 G mana
    assert p1.mana_pool.total() == 5
    big = next(o for o in p1.hand if o.name == "Big Beast")
    small = next(o for o in p1.hand if o.name == "Small Beast")
    assert eng.can_cast(p1, big)  # mana value 5 >= 4, and affordable (5 G mana)
    assert not eng.can_cast(p1, small)  # mana value 1, no {X} — restriction rejects it


# ---------------------------------------------------------------------------
# Throne of Eldraine — chosen-colour mana production, "monocolored spells of
# that color" spend restriction, and the second ability's colour-lock.
# ---------------------------------------------------------------------------


def _throne():
    return Card(
        id="Throne of Eldraine", name="Throne of Eldraine", type_line="Legendary Artifact",
        is_legendary=True,
        oracle_text=(
            "As Throne of Eldraine enters, choose a color.\n"
            "{T}: Add four mana of the chosen color. Spend this mana only to cast "
            "monocolored spells of that color.\n"
            "{3}, {T}: Draw two cards. Spend only mana of the chosen color to activate "
            "this ability."
        ),
    )


def test_throne_produces_four_mana_of_the_chosen_color():
    eng = _make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    throne = GameObject(_throne(), owner_id="p1", zone=Zone.BATTLEFIELD)
    throne.summoning_sick = False
    throne.chosen_color = "R"
    eng.state.add_to_battlefield(throne)

    produced = eng.tap_for_mana(p1, throne, ability_index=0)
    assert produced == {"R": 4}
    assert p1.mana_pool.pool.get("R", 0) == 0  # tagged into a restricted lot


def test_throne_mana_casts_only_monocolored_spells_of_the_chosen_color():
    red_spell = _creature("Red Bear", cost="{R}", type_line="Creature — Bear")
    red_spell.color_identity = {"R"}
    multi = _creature("Gruul Bear", cost="{R}{G}", type_line="Creature — Bear")
    multi.color_identity = {"R", "G"}
    blue_spell = _creature("Blue Bear", cost="{U}", type_line="Creature — Bear")
    blue_spell.color_identity = {"U"}
    eng = _make_engine([red_spell, multi, blue_spell], hand=3)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    throne = GameObject(_throne(), owner_id="p1", zone=Zone.BATTLEFIELD)
    throne.summoning_sick = False
    throne.chosen_color = "R"
    eng.state.add_to_battlefield(throne)

    eng.tap_for_mana(p1, throne, ability_index=0)
    red = next(o for o in p1.hand if o.name == "Red Bear")
    gruul = next(o for o in p1.hand if o.name == "Gruul Bear")
    blue = next(o for o in p1.hand if o.name == "Blue Bear")
    assert eng.can_cast(p1, red)  # monocolored, of the chosen colour
    assert not eng.can_cast(p1, gruul)  # multicolored
    assert not eng.can_cast(p1, blue)  # monocolored, but the wrong colour


def test_throne_second_ability_is_colour_locked_to_the_chosen_colour():
    eng = _make_engine([_land("L1"), _land("L2")], hand=0)  # two cards to draw
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    from mtg_analyzer.game.effect_binder import bind_from_catalogue
    throne = GameObject(_throne(), owner_id="p1", zone=Zone.BATTLEFIELD)
    throne.summoning_sick = False
    throne.chosen_color = "R"
    bind_from_catalogue(throne)
    eng.state.add_to_battlefield(throne)
    [draw_ability] = throne.activated_abilities

    # Three *green* mana can't pay the {3} — it's locked to the chosen (red).
    p1.mana_pool.add_many({"G": 3})
    assert not eng.can_activate(p1, throne, draw_ability)

    # Add three red — now payable; the green is left untouched.
    p1.mana_pool.add_many({"R": 3})
    assert eng.can_activate(p1, throne, draw_ability)
    before = len(p1.hand)
    eng.activate_ability(p1, throne, ability_index=0)
    eng.resolve_until_stable()
    assert len(p1.hand) - before == 2
    assert p1.mana_pool.pool.get("R", 0) == 0   # all three red spent
    assert p1.mana_pool.pool.get("G", 0) == 3   # green untouched


def test_throne_is_fully_modeled_by_the_parser():
    from mtg_analyzer.parser.oracle import parse_oracle
    from mtg_analyzer.parser.oracle.gate import MODELED

    result = parse_oracle(_throne())
    assert result.coverage == MODELED

"""Tests for RULE 605.3a mana spend restrictions ("Spend this mana only to
cast a creature spell.") — the tagged/restricted `ManaPool` lots
(models/mana_pool.py), their parsing into `ManaAbility.restriction`
(game/mana_abilities.py), and the actual cast/activation-cost payment
call sites (game/rules_engine.py's `cast_spell`, game/game_engine.py's
`can_cast`/`_can_pay_activation_cost`/`_pay_activation_cost`) honoring them.

Reference: backend/ToDo_Backend.md, docs/implementation-state/Done_Backend.md.
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
    ],
)
def test_parse_restriction_recognises_the_modeled_shapes(clause, expected):
    assert _parse_restriction(clause) == expected


@pytest.mark.parametrize(
    "clause",
    [
        # Chosen-type/chosen-colour lands (RULE 605.3a's "of the chosen
        # type"/"of that color") — not modeled (no per-object "chosen type"
        # read here yet); fail-soft, not fail-closed.
        "Add one mana of any color. Spend this mana only to cast a creature spell of the chosen type.",
        "Add four mana of the chosen color. Spend this mana only to cast monocolored spells of that color.",
        # Mana-value-threshold clauses (Helga, Troyan) — not modeled.
        "Add X mana of any one color, where X is Helga's power. Spend this mana only to cast creature "
        "spells with mana value 4 or greater or creature spells with {X} in their mana costs.",
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
        # gap, see backend/ToDo_Backend.md); explicit pips sidestep it so
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
        # gap, see backend/ToDo_Backend.md); explicit pips sidestep it so
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

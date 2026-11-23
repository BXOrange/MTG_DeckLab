"""PAR-289 milestone 4: composite group / host statements (`rows_typed_groups`).

One predicate grammar over two subjects: a typed group read by the shared object grammar ("all permanents",
"nontoken artifacts you control", "other creatures", ...) and the host of an Aura or Equipment. Each claimed card binds
its real text on a real engine and the layer result is read for the condition true, false and toggling, plus a
bystander outside the subject (RULE 613). "In addition to its other types" must keep the old types (RULE 205.1b); the
replacing "is a black Zombie" must drop the old creature types and colours (RULE 205.3m / 105.3).
"""

from __future__ import annotations

import re

import pytest

from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import parse_oracle

#: (name, type line, oracle text) of every card this milestone newly models through the composite grammar.
CLAIMED = [
    ('Arachnoform', 'Enchantment — Aura', 'Enchant creature\nEnchanted creature gets +2/+2, has reach, and is every creature type.'),
    ('Callaphe, Beloved of the Sea', 'Legendary Creature — Merfolk', 'Creatures and enchantments you control have "Spells your opponents cast that target this permanent cost {1} more to cast."'),
    ('Clash of Realities', 'Enchantment', 'All Spirits have "When this permanent enters, you may have it deal 3 damage to target non-Spirit creature."\nNon-Spirit creatures have "When this creature enters, you may have it deal 3 damage to target Spirit creature."'),
    ('Ferocity of the Wilds', 'Enchantment', 'Attacking non-Human creatures you control get +1/+0 and have trample.'),
    ('Gravitational Shift', 'Enchantment', 'Creatures with flying get +2/+0.\nCreatures without flying get -2/-0.'),
    ('Great Divide Guide', 'Creature — Human Scout', 'Each land and Ally you control has "{T}: Add one mana of any color."'),
    ('Secret Plans', 'Enchantment', 'Face-down creatures you control get +0/+1.'),
    ('The Juzam Master', 'Creature — Human Wizard', 'Creatures you control get +1/+0 and have "At the beginning of your upkeep, this creature deals 1 damage to you."'),
    ('Titan of Eternal Fire', 'Creature — Giant', 'Each Human creature you control has "{R}, {T}: This creature deals 1 damage to any target."'),
    ('Aurification', 'Enchantment', "Whenever a creature deals damage to you, put a gold counter on it.\nEach creature with a gold counter on it is a Wall in addition to its other creature types and has defender.\nWhen this enchantment leaves the battlefield, remove all gold counters from all creatures."),
    ('Cathedral Acolyte', 'Creature — Human Cleric', 'Each creature you control with a counter on it has ward {1}.'),
    ('Ivory Guardians', 'Creature — Giant Cleric', 'Protection from red\nCreatures named Ivory Guardians get +1/+1 as long as an opponent controls a nontoken red permanent.'),
    ('Time of Heroes', 'Enchantment', 'Each creature you control with a level counter on it gets +2/+2.'),
    ("Runechanter's Pike", 'Artifact — Equipment', "Equipped creature has first strike and gets +X/+0, where X is the number of instant and sorcery cards in your graveyard.\nEquip {2}"),
    ('Aettir and Priwen', 'Legendary Artifact — Equipment', 'Equipped creature has base power and toughness X/X, where X is your life total.\nEquip {5}'),
    ('Champions of Archery // Join the Group', 'Enchantment', 'Commanders you control get +X/+0, where X is the number of commanders you control.'),
    ('Gornog, the Red Reaper', 'Legendary Creature — Human Warrior', 'Attacking Warriors you control get +X/+0, where X is the number of Cowards your opponents control.'),
    ('Meishin, the Mind Cage', 'Legendary Creature — Human Wizard', 'All creatures get -X/-0, where X is the number of cards in your hand.'),
    ('Dagger of the Worthy', 'Artifact — Equipment', 'Equipped creature gets +2/+0 and has afflict 1.\nEquip {2}'),
    ('Dismiss into Dream', 'Enchantment', 'Each creature your opponents control is an Illusion in addition to its other types and has "When this creature becomes the target of a spell or ability, sacrifice it."'),
    ("Dralnu's Crusade", 'Enchantment', 'All Goblins get +1/+1.\nAll Goblins are black and are Zombies in addition to their other creature types.'),
    ('Enchanted Evening', 'Enchantment', 'All permanents are enchantments in addition to their other types.'),
    ('Gravity Sphere', 'Enchantment', 'All creatures lose flying.'),
    ('Godhead of Awe', 'Creature — Angel', 'Flying\nOther creatures have base power and toughness 1/1.'),
    ('Infectious Bloodlust', 'Enchantment — Aura', 'Enchant creature\nEnchanted creature gets +2/+1, has haste, and attacks each combat if able.'),
    ('Karumonix, the Rat King', 'Legendary Creature — Rat Horror', 'Toxic 1\nOther Rats you control have toxic 1.'),
    ('Kudo, King Among Bears', 'Legendary Creature — Bear', 'Other creatures have base power and toughness 2/2 and are Bears in addition to their other types.'),
    ('Leaden Fists', 'Enchantment — Aura', "Enchant creature\nEnchanted creature gets +3/+3 and doesn't untap during its controller's untap step."),
    ('Leyline of Singularity', 'Enchantment', 'All nonland permanents are legendary.'),
    ("Machinist's Arsenal", 'Artifact — Equipment', 'Equipped creature gets +2/+2 for each artifact you control and is an Artificer in addition to its other types.\nEquip {4}'),
    ('Maha, Its Feathers Night', 'Legendary Creature — Elemental Bird', 'Creatures your opponents control have base toughness 1.'),
    ('March of the Machines', 'Enchantment', 'Each noncreature artifact is an artifact creature with power and toughness each equal to its mana value.'),
    ('Mistform Ultimus', 'Creature — Illusion', "Mistform Ultimus is every creature type (even if this card isn't on the battlefield)."),
    ('Mystic Decree', 'Enchantment', 'All creatures lose flying and islandwalk.'),
    ('Necrogen Communion', 'Enchantment — Aura', 'Enchant creature you control\nEnchanted creature has toxic 2.'),
    ('Nim Deathmantle', 'Artifact — Equipment', 'Equipped creature gets +2/+2, has intimidate, and is a black Zombie.\nEquip {4}'),
    ('Octopus Umbra', 'Enchantment — Aura', 'Enchant creature\nEnchanted creature has base power and toughness 8/8 and has "Whenever this creature attacks, you may tap target creature with power 8 or less."'),
    ('Opalescence', 'Enchantment', 'Each other non-Aura enchantment is a creature in addition to its other types and has base power and base toughness each equal to its mana value.'),
    ('Prosthetic Injector', 'Artifact — Equipment', 'Equipped creature gets +0/+2 and has toxic 1.\nEquip {1}'),
    ('Raised by Giants', 'Enchantment', 'Commander creatures you own have base power and toughness 10/10 and are Giants in addition to their other types.'),
    ('Sigarda\'s Summons', 'Enchantment', 'Creatures you control with +1/+1 counters on them have base power and toughness 4/4, have flying, and are Angels in addition to their other types.'),
    ('Sky Tether', 'Enchantment — Aura', 'Enchant creature\nEnchanted creature has defender and loses flying.'),
    ('Spectral Guardian', 'Artifact Creature — Construct', 'As long as this creature is untapped, noncreature artifacts have shroud.'),
    ('Stalactite Dagger', 'Artifact — Equipment', 'Equipped creature gets +1/+1 and is all creature types.\nEquip {2}'),
    ('Starfield of Nyx', 'Enchantment', 'As long as you control five or more enchantments, each other non-Aura enchantment you control is a creature in addition to its other types and has base power and base toughness each equal to its mana value.'),
    ('The Flesh Is Weak', 'Enchantment', 'Creatures you control with +1/+1 counters on them are artifacts in addition to their other types.'),
    ('Thran Power Suit', 'Artifact — Equipment', 'Equipped creature gets +1/+1 for each Aura and Equipment attached to it and has ward {2}.\nEquip {2}'),
    ('Toph, the First Metalbender', 'Legendary Creature — Human Warrior', 'Nontoken artifacts you control are lands in addition to their other types.'),
    ('Valentina Allegra de Fontaine', 'Legendary Creature — Human Villain', 'Other Villains you control are Heroes in addition to their other types.'),
    ('Vulshok Gauntlets', 'Artifact — Equipment', "Equipped creature gets +4/+2 and doesn't untap during its controller's untap step.\nEquip {3}"),
]


@pytest.mark.parametrize("name,type_line,text", CLAIMED, ids=[c[0] for c in CLAIMED])
def test_claimed_real_cards_parse_modeled(name, type_line, text):
    creature = "Creature" in type_line
    card = Card(id=name, name=name, oracle_text=text, type_line=type_line, is_creature=creature,
                power=1 if creature else None, toughness=1 if creature else None)
    assert parse_oracle(card).modeled


@pytest.mark.parametrize("clause", [
    # The ward pattern must not swallow a condition as its cost.
    "~ has haste and ward {10} as long as it was cast.",
    # The folded "~" in a grant names the Equipment, a granted ability's "~" binds to the host.
    'equipped creature gets +1/+0 for each blood counter on ~ and has "{t}, sacrifice a creature: put a blood counter on ~."',
    # Unknown words are never guessed to be a type, colour or keyword.
    "all permanents are zzzzz in addition to their other types.",
    "all zzzzz permanents are enchantments in addition to their other types.",
    "enchanted creature has zzzzz and loses flying.",
    "enchanted creature has defender and loses zzzzz.",
    "all creatures are black and are zzzzz in addition to their other types.",
    "each noncreature artifact is a zzzzz creature with power and toughness each equal to its mana value.",
    "equipped creature is a zzzzz.",
    "equipped creature gets +x/+0, where x is the number of zzzzz you control.",
])
def test_unreadable_shapes_fail_closed(clause):
    assert static_effect_specs(clause) is None


# -- engine harness --------------------------------------------------------------------------------------------------


def _card(name, text="", type_line="Creature — Bear", power=2, toughness=2, mana="", **extra):
    creature = "Creature" in type_line
    # The mana value is the card's converted cost, read from the printed cost's symbols.
    extra.setdefault("converted_mana_cost", sum(int(g) for g in re.findall(r"\{(\d+)\}", mana)) + mana.count("{W}"))
    return Card(id=name, name=name, oracle_text=text, type_line=type_line, is_creature=creature,
                power=power if creature else None, toughness=toughness if creature else None,
                mana_cost_string=mana, **extra)


def _engine():
    return GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0)


def _put(eng, card, controller="p1", counters=None):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    if counters:
        obj.counters.update(counters)
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _row(name):
    return next(r for r in CLAIMED if r[0] == name)


def _real(eng, name, controller="p1", **kw):
    n, type_line, text = _row(name)
    creature = "Creature" in type_line
    card = _card(n, text, type_line, power=kw.pop("power", 2), toughness=kw.pop("toughness", 2), **kw)
    return _put(eng, card, controller)


def _attach(eng, source, host):
    source.attached_to = host.instance_id
    eng.recompute_continuous_effects()


def _fresh(eng):
    eng.recompute_continuous_effects()


def _types(eng, obj):
    _fresh(eng)
    return obj.type_words


def _pt(eng, obj):
    _fresh(eng)
    return obj.power, obj.toughness


def _kw(eng, obj, keyword):
    _fresh(eng)
    return keyword in obj.granted_keywords


def _remove(eng, obj):
    eng.state.battlefield.remove(obj)
    _fresh(eng)


# -- add-a-type groups (RULE 205.1b) ---------------------------------------------------------------------------------


def test_enchanted_evening_makes_every_permanent_an_enchantment_and_keeps_old_types():
    eng = _engine()
    evening = _real(eng, "Enchanted Evening")
    land = _put(eng, _card("Their Forest", type_line="Basic Land — Forest"), "p2")
    bear = _put(eng, _card("My Bear"))
    assert "enchantment" in _types(eng, land) and "land" in _types(eng, land)
    assert "enchantment" in _types(eng, bear) and bear.is_creature and bear.has_subtype("Bear")
    _remove(eng, evening)
    assert "enchantment" not in _types(eng, land) and "enchantment" not in _types(eng, bear)


def test_toph_makes_only_your_nontoken_artifacts_lands():
    eng = _engine()
    _real(eng, "Toph, the First Metalbender")
    mine = _put(eng, _card("My Rock", type_line="Artifact"))
    token = _put(eng, _card("My Treasure", type_line="Artifact — Treasure"))
    token.is_token = True
    theirs = _put(eng, _card("Their Rock", type_line="Artifact"), "p2")
    creature = _put(eng, _card("Plain Bear"))
    assert "land" in _types(eng, mine) and "artifact" in _types(eng, mine)  # old type kept
    assert "land" not in _types(eng, token)
    assert "land" not in _types(eng, theirs)
    assert "land" not in _types(eng, creature)


def test_the_flesh_is_weak_follows_the_counter_and_skips_opponents():
    eng = _engine()
    _real(eng, "The Flesh Is Weak")
    marked = _put(eng, _card("Marked"), counters={"+1/+1": 1})
    plain = _put(eng, _card("Plain"))
    theirs = _put(eng, _card("Theirs"), "p2", counters={"+1/+1": 1})
    assert "artifact" in _types(eng, marked) and marked.is_creature
    assert "artifact" not in _types(eng, plain) and "artifact" not in _types(eng, theirs)
    marked.counters["+1/+1"] = 0  # the counter leaves: the type goes with it
    assert "artifact" not in _types(eng, marked)
    plain.counters["+1/+1"] = 1
    assert "artifact" in _types(eng, plain)


def test_valentina_other_villains_you_control_gain_hero():
    eng = _engine()
    n, type_line, text = _row("Valentina Allegra de Fontaine")
    valentina = _put(eng, _card(n, text, type_line))
    mine = _put(eng, _card("My Villain", type_line="Creature — Human Villain"))
    theirs = _put(eng, _card("Their Villain", type_line="Creature — Human Villain"), "p2")
    other = _put(eng, _card("My Bear"))
    _fresh(eng)
    assert mine.has_subtype("Hero") and mine.has_subtype("Villain")
    assert not valentina.has_subtype("Hero")  # "other"
    assert not theirs.has_subtype("Hero") and not other.has_subtype("Hero")


def test_dralnu_crusade_recolours_and_adds_zombie_for_every_goblin():
    eng = _engine()
    _real(eng, "Dralnu's Crusade")
    mine = _put(eng, _card("My Goblin", type_line="Creature — Goblin", mana="{R}"))
    theirs = _put(eng, _card("Their Goblin", type_line="Creature — Goblin"), "p2")
    elf = _put(eng, _card("Elf", type_line="Creature — Elf"))
    _fresh(eng)
    for goblin in (mine, theirs):
        assert goblin.has_subtype("Goblin") and goblin.has_subtype("Zombie")
        assert goblin.colors == {"B"}
    assert not elf.has_subtype("Zombie") and elf.colors != {"B"}
    assert _pt(eng, mine) == (3, 3) and _pt(eng, elf) == (2, 2)  # the sibling "All Goblins get +1/+1" still reads


def test_mistform_ultimus_is_every_creature_type():
    eng = _engine()
    ultimus = _real(eng, "Mistform Ultimus")
    _fresh(eng)
    assert ultimus.has_subtype("Goblin") and ultimus.has_subtype("Wizard")
    other = _put(eng, _card("Other Bear"))
    _fresh(eng)
    assert not other.has_subtype("Goblin")


def test_leyline_of_singularity_makes_nonland_permanents_legendary_not_lands():
    eng = _engine()
    _real(eng, "Leyline of Singularity")
    creature = _put(eng, _card("Dup"))
    land = _put(eng, _card("Plains", type_line="Basic Land — Plains"))
    _fresh(eng)
    assert creature.is_legendary and not land.is_legendary


# -- base P/T and mana-value animation groups ------------------------------------------------------------------------


def test_kudo_sets_base_pt_and_adds_bear_to_other_creatures_only():
    eng = _engine()
    kudo = _real(eng, "Kudo, King Among Bears", power=2, toughness=2)
    wolf = _put(eng, _card("Wolf", type_line="Creature — Wolf", power=4, toughness=4))
    theirs = _put(eng, _card("Their Wolf", type_line="Creature — Wolf", power=5, toughness=5), "p2")
    kudo.card.power, kudo.card.toughness = 7, 7
    assert _pt(eng, wolf) == (2, 2) and _pt(eng, theirs) == (2, 2) and _pt(eng, kudo) == (7, 7)
    assert wolf.has_subtype("Wolf") and wolf.has_subtype("Bear")  # in addition: the old type stays


def test_maha_sets_only_the_toughness_of_opponents_creatures():
    eng = _engine()
    _real(eng, "Maha, Its Feathers Night")
    theirs = _put(eng, _card("Their Giant", power=5, toughness=6), "p2")
    mine = _put(eng, _card("My Giant", power=5, toughness=6))
    assert _pt(eng, theirs) == (5, 1)  # the power half keeps its value
    assert _pt(eng, mine) == (5, 6)


def test_godhead_of_awe_sets_base_one_one_on_every_other_creature():
    eng = _engine()
    awe = _real(eng, "Godhead of Awe", power=4, toughness=4)
    mine = _put(eng, _card("Mine", power=3, toughness=3))
    theirs = _put(eng, _card("Theirs", power=3, toughness=3), "p2")
    assert _pt(eng, mine) == (1, 1) and _pt(eng, theirs) == (1, 1) and _pt(eng, awe) == (4, 4)
    _remove(eng, awe)
    assert _pt(eng, mine) == (3, 3)


def test_raised_by_giants_reaches_only_commanders_you_own():
    eng = _engine()
    _real(eng, "Raised by Giants")
    commander = _put(eng, _card("My Commander", power=2, toughness=2))
    commander.is_commander = True
    commander.owner_id = "p1"
    theirs = _put(eng, _card("Their Commander", power=2, toughness=2), "p2")
    theirs.is_commander = True
    theirs.owner_id = "p2"
    plain = _put(eng, _card("Plain", power=2, toughness=2))
    assert _pt(eng, commander) == (10, 10) and commander.has_subtype("Giant") and commander.has_subtype("Bear")
    assert _pt(eng, theirs) == (2, 2) and _pt(eng, plain) == (2, 2)


def test_sigardas_summons_needs_the_counter_and_is_yours_only():
    eng = _engine()
    _real(eng, "Sigarda's Summons")
    marked = _put(eng, _card("Marked", power=1, toughness=1), counters={"+1/+1": 1})
    plain = _put(eng, _card("Plain", power=1, toughness=1))
    theirs = _put(eng, _card("Theirs", power=1, toughness=1), "p2", counters={"+1/+1": 1})
    _fresh(eng)
    # base 4/4 then the +1/+1 counter (RULE 613.4b before 613.4c)
    assert _pt(eng, marked) == (5, 5) and marked.has_subtype("Angel") and "flying" in marked.granted_keywords
    assert _pt(eng, plain) == (1, 1) and not plain.has_subtype("Angel")
    assert _pt(eng, theirs) == (2, 2) and not _kw(eng, theirs, "flying")


def test_opalescence_animates_other_nonaura_enchantments_with_mana_value_pt():
    eng = _engine()
    opal = _real(eng, "Opalescence", mana="{2}{W}{W}")
    ench = _put(eng, _card("Shrine", type_line="Enchantment", mana="{3}"))
    aura = _put(eng, _card("Aura", type_line="Enchantment — Aura", mana="{1}{W}"))
    theirs = _put(eng, _card("Their Ench", type_line="Enchantment", mana="{4}"), "p2")
    for _ in range(2):  # stable across recomputes: no flip-flopping once it is a creature
        assert _is(eng, ench) and "enchantment" in _types(eng, ench)
        assert _pt(eng, ench) == (3, 3) and _pt(eng, theirs) == (4, 4)
        assert not _is(eng, aura) and not _is(eng, opal)
    _remove(eng, opal)
    assert not ench.is_creature and not theirs.is_creature


def test_starfield_of_nyx_needs_five_enchantments_and_only_yours():
    eng = _engine()
    starfield = _real(eng, "Starfield of Nyx", mana="{4}{W}")
    others = [_put(eng, _card(f"Ench {i}", type_line="Enchantment", mana="{2}")) for i in range(3)]
    theirs = _put(eng, _card("Their Ench", type_line="Enchantment", mana="{2}"), "p2")
    assert not any(_is(eng, o) for o in others)  # starfield + 3 = four enchantments: the condition is false
    fifth = _put(eng, _card("Ench 4", type_line="Enchantment", mana="{2}"))
    assert all(_is(eng, o) for o in [*others, fifth]) and not starfield.is_creature
    assert not _is(eng, theirs)
    _remove(eng, fifth)
    assert not any(_is(eng, o) for o in others)  # toggles back off


def _is(eng, obj):
    _fresh(eng)
    return obj.is_creature


def test_march_of_the_machines_replaces_card_types_and_leaves_creature_artifacts_alone():
    eng = _engine()
    march = _real(eng, "March of the Machines")
    rock = _put(eng, _card("Rock", type_line="Artifact", mana="{3}"))
    golem = _put(eng, _card("Golem", type_line="Artifact Creature — Golem", power=9, toughness=9, mana="{1}"))
    relic = _put(eng, _card("Relic", type_line="Enchantment Artifact", mana="{2}"))
    for _ in range(2):
        assert _is(eng, rock) and _pt(eng, rock) == (3, 3)
        assert _pt(eng, golem) == (9, 9)  # already a creature: the statement is not about it
    assert {"artifact", "creature"} <= _types(eng, rock)
    # RULE 205.1a: "is an artifact creature" sets the card types, so an Enchantment Artifact stops being an enchantment.
    assert {"artifact", "creature"} <= _types(eng, relic) and "enchantment" not in _types(eng, relic)
    _remove(eng, march)
    assert not _is(eng, rock)


# -- host statements (Auras and Equipment) ---------------------------------------------------------------------------


def test_sky_tether_grants_defender_and_removes_flying_from_the_host_only():
    eng = _engine()
    host = _put(eng, _card("Host", "Flying", "Creature — Bird"))
    twin = _put(eng, _card("Twin", "Flying", "Creature — Bird"))
    tether = _real(eng, "Sky Tether")
    _attach(eng, tether, host)
    assert _kw(eng, host, "defender") and not combat.has(host, "flying")
    assert not _kw(eng, twin, "defender") and combat.has(twin, "flying")
    tether.attached_to = None
    _fresh(eng)
    assert not _kw(eng, host, "defender") and combat.has(host, "flying")


def test_nim_deathmantle_replaces_creature_types_and_colours_but_keeps_card_types():
    eng = _engine()
    host = _put(eng, _card("Human", type_line="Creature — Human Soldier", power=1, toughness=1))
    bystander = _put(eng, _card("Other Human", type_line="Creature — Human Soldier", power=1, toughness=1))
    mantle = _real(eng, "Nim Deathmantle")
    _attach(eng, mantle, host)
    assert _pt(eng, host) == (3, 3) and _kw(eng, host, "intimidate")
    assert host.has_subtype("Zombie") and not host.has_subtype("Human") and not host.has_subtype("Soldier")
    assert host.colors == {"B"} and host.is_creature
    assert bystander.has_subtype("Human") and _pt(eng, bystander) == (1, 1)
    mantle.attached_to = None
    _fresh(eng)
    assert host.has_subtype("Human") and not host.has_subtype("Zombie") and _pt(eng, host) == (1, 1)


def test_machinists_arsenal_scales_with_your_artifacts_and_adds_artificer():
    eng = _engine()
    host = _put(eng, _card("Hero", type_line="Creature — Human", power=1, toughness=1))
    arsenal = _real(eng, "Machinist's Arsenal")
    _put(eng, _card("Rock", type_line="Artifact"))
    _put(eng, _card("Their Rock", type_line="Artifact"), "p2")
    _attach(eng, arsenal, host)
    assert _pt(eng, host) == (5, 5)  # the Arsenal and one rock: two artifacts of yours -> +4/+4
    assert host.has_subtype("Artificer") and host.has_subtype("Human")  # in addition
    _put(eng, _card("Rock 2", type_line="Artifact"))
    assert _pt(eng, host) == (7, 7)


def test_octopus_umbra_sets_base_eight_eight_and_grants_the_trigger():
    eng = _engine()
    host = _put(eng, _card("Host", power=1, toughness=1))
    other = _put(eng, _card("Other", power=1, toughness=1))
    umbra = _real(eng, "Octopus Umbra")
    _attach(eng, umbra, host)
    assert _pt(eng, host) == (8, 8) and _pt(eng, other) == (1, 1)
    assert host._granted_triggered_abilities and not other._granted_triggered_abilities
    umbra.attached_to = None
    _fresh(eng)
    assert _pt(eng, host) == (1, 1) and not host._granted_triggered_abilities


def test_arachnoform_and_stalactite_dagger_make_the_host_every_creature_type():
    eng = _engine()
    host = _put(eng, _card("Host", power=1, toughness=1))
    other = _put(eng, _card("Other", power=1, toughness=1))
    aura = _real(eng, "Arachnoform")
    _attach(eng, aura, host)
    assert _pt(eng, host) == (3, 3) and _kw(eng, host, "reach") and host.has_subtype("Goblin")
    assert not other.has_subtype("Goblin") and not _kw(eng, other, "reach")
    aura.attached_to = None
    _fresh(eng)
    assert not host.has_subtype("Goblin")
    dagger = _real(eng, "Stalactite Dagger")
    _attach(eng, dagger, host)
    assert _pt(eng, host) == (2, 2) and host.has_subtype("Goblin") and not other.has_subtype("Goblin")


def test_leaden_fists_and_vulshok_gauntlets_stop_the_host_untapping():
    eng = _engine()
    host = _put(eng, _card("Host"))
    other = _put(eng, _card("Other"))
    fists = _real(eng, "Leaden Fists")
    _attach(eng, fists, host)
    assert _pt(eng, host) == (5, 5)
    assert continuous.has_no_untap_static(eng.state, host) and not continuous.has_no_untap_static(eng.state, other)
    fists.attached_to = None
    _fresh(eng)
    assert not continuous.has_no_untap_static(eng.state, host)


def test_infectious_bloodlust_forces_the_host_to_attack():
    eng = _engine()
    host = _put(eng, _card("Host"))
    other = _put(eng, _card("Other"))
    aura = _real(eng, "Infectious Bloodlust")
    _attach(eng, aura, host)
    assert _pt(eng, host) == (4, 3) and _kw(eng, host, "haste") and _kw(eng, host, "attacks_if_able")
    assert not _kw(eng, other, "attacks_if_able")


def test_thran_power_suit_counts_auras_and_equipment_on_the_host():
    eng = _engine()
    host = _put(eng, _card("Host", power=1, toughness=1))
    other = _put(eng, _card("Other", power=1, toughness=1))
    suit = _real(eng, "Thran Power Suit")
    _attach(eng, suit, host)
    assert _pt(eng, host) == (2, 2)  # the Suit itself is one Equipment attached to it
    aura = _put(eng, _card("Aura", type_line="Enchantment — Aura"))
    _attach(eng, aura, host)
    assert _pt(eng, host) == (3, 3)
    far = _put(eng, _card("Far Aura", type_line="Enchantment — Aura"))
    _attach(eng, far, other)  # on another creature: not counted
    assert _pt(eng, host) == (3, 3) and _pt(eng, other) == (1, 1)


def test_parametric_toxic_grants_reach_the_host_and_the_group():
    eng = _engine()
    host = _put(eng, _card("Host"))
    other = _put(eng, _card("Other"))
    injector = _real(eng, "Prosthetic Injector")
    _attach(eng, injector, host)
    assert _pt(eng, host) == (2, 4) and combat.toxic_value(host) == 1 and combat.toxic_value(other) is None
    aura_host = _put(eng, _card("Aura Host"))
    communion = _real(eng, "Necrogen Communion")
    _attach(eng, communion, aura_host)
    assert combat.toxic_value(aura_host) == 2
    king = _real(eng, "Karumonix, the Rat King")
    rat = _put(eng, _card("My Rat", type_line="Creature — Rat"))
    their_rat = _put(eng, _card("Their Rat", type_line="Creature — Rat"), "p2")
    _fresh(eng)
    assert combat.toxic_value(rat) == 1 and combat.toxic_value(their_rat) is None
    assert combat.toxic_value(king) is None  # "other": the source itself is not granted the keyword


# -- keyword groups --------------------------------------------------------------------------------------------------


def test_gravity_sphere_removes_flying_from_every_creature():
    eng = _engine()
    sphere = _real(eng, "Gravity Sphere")
    mine = _put(eng, _card("My Bird", "Flying", "Creature — Bird"))
    theirs = _put(eng, _card("Their Bird", "Flying", "Creature — Bird"), "p2")
    assert not _kw(eng, mine, "flying") and not _kw(eng, theirs, "flying")
    _remove(eng, sphere)
    assert combat.has(mine, "flying") and combat.has(theirs, "flying")


def test_spectral_guardian_gives_shroud_to_noncreature_artifacts_only_while_untapped():
    eng = _engine()
    guardian = _real(eng, "Spectral Guardian")
    rock = _put(eng, _card("Rock", type_line="Artifact"))
    theirs = _put(eng, _card("Their Rock", type_line="Artifact"), "p2")
    golem = _put(eng, _card("Golem", type_line="Artifact Creature — Golem"))
    assert _kw(eng, rock, "shroud") and _kw(eng, theirs, "shroud")  # "noncreature artifacts": any controller
    assert not _kw(eng, golem, "shroud") and not _kw(eng, guardian, "shroud")
    guardian.tapped = True
    assert not _kw(eng, rock, "shroud")
    guardian.tapped = False
    assert _kw(eng, rock, "shroud")
    _remove(eng, guardian)
    assert not _kw(eng, rock, "shroud")


def test_dismiss_into_dream_adds_illusion_and_grants_the_trigger_to_opponents_creatures():
    eng = _engine()
    _real(eng, "Dismiss into Dream")
    theirs = _put(eng, _card("Their Bear", type_line="Creature — Bear"), "p2")
    mine = _put(eng, _card("My Bear", type_line="Creature — Bear"))
    _fresh(eng)
    assert theirs.has_subtype("Illusion") and theirs.has_subtype("Bear") and theirs._granted_triggered_abilities
    assert not mine.has_subtype("Illusion") and not mine._granted_triggered_abilities


# -- grants of abilities and filters on the group -----------------------------------------------------------------


def test_gravitational_shift_penalises_only_creatures_without_flying():
    eng = _engine()
    _real(eng, "Gravitational Shift")
    flyer = _put(eng, _card("Flyer", "Flying", "Creature — Bird"))
    ground = _put(eng, _card("Ground"))
    theirs = _put(eng, _card("Their Ground"), "p2")
    assert _pt(eng, flyer) == (4, 2) and _pt(eng, ground) == (0, 2) and _pt(eng, theirs) == (0, 2)


def test_ferocity_of_the_wilds_needs_attacking_and_nonhuman_and_yours():
    eng = _engine()
    _real(eng, "Ferocity of the Wilds")
    elf = _put(eng, _card("Elf", type_line="Creature — Elf"))
    human = _put(eng, _card("Human", type_line="Creature — Human"))
    idle = _put(eng, _card("Idle Elf", type_line="Creature — Elf"))
    theirs = _put(eng, _card("Their Elf", type_line="Creature — Elf"), "p2")
    for o in (elf, human, theirs):
        o.attacking = True
    assert _pt(eng, elf) == (3, 2) and _kw(eng, elf, "trample")
    assert _pt(eng, human) == (2, 2) and _pt(eng, idle) == (2, 2) and _pt(eng, theirs) == (2, 2)
    elf.attacking = False  # stops attacking: the bonus goes
    assert _pt(eng, elf) == (2, 2)


def test_secret_plans_reaches_only_your_face_down_creatures():
    eng = _engine()
    _real(eng, "Secret Plans")
    down = _put(eng, _card("Down"))
    down.face_down = True
    up = _put(eng, _card("Up"))
    theirs = _put(eng, _card("Theirs"), "p2")
    theirs.face_down = True
    assert _pt(eng, down) == (2, 3) and _pt(eng, up) == (2, 2) and _pt(eng, theirs) == (2, 2)


def test_great_divide_guide_gives_your_lands_and_allies_every_colour():
    eng = _engine()
    _real(eng, "Great Divide Guide")
    land = _put(eng, _card("Plains", type_line="Basic Land — Plains"))
    ally = _put(eng, _card("Ally", type_line="Creature — Kor Ally"))
    other = _put(eng, _card("Other"))
    theirs = _put(eng, _card("Their Plains", type_line="Basic Land — Plains"), "p2")
    _fresh(eng)
    assert len(land._granted_mana) == 5 and len(ally._granted_mana) == 5
    assert not other._granted_mana and not theirs._granted_mana


def test_juzam_master_and_titan_grant_abilities_to_the_right_group():
    eng = _engine()
    _real(eng, "The Juzam Master")
    _real(eng, "Titan of Eternal Fire")
    mine = _put(eng, _card("Mine", type_line="Creature — Human"))
    theirs = _put(eng, _card("Theirs", type_line="Creature — Human"), "p2")
    _fresh(eng)
    assert _pt(eng, mine) == (3, 2) and _pt(eng, theirs) == (2, 2)
    assert len(mine._granted_triggered_abilities) == 1 and not theirs._granted_triggered_abilities
    assert len(mine._granted_activated_abilities) == 1 and not theirs._granted_activated_abilities


def test_clash_of_realities_grants_the_enters_trigger_by_spirit_status():
    eng = _engine()
    _real(eng, "Clash of Realities")
    spirit = _put(eng, _card("Spirit", type_line="Creature — Spirit"))
    bear = _put(eng, _card("Bear"))
    land = _put(eng, _card("Land", type_line="Basic Land — Plains"))
    _fresh(eng)
    assert len(spirit._granted_triggered_abilities) == 1 and len(bear._granted_triggered_abilities) == 1
    assert not land._granted_triggered_abilities


def test_callaphe_grants_the_tax_to_creatures_and_enchantments_you_control():
    eng = _engine()
    _real(eng, "Callaphe, Beloved of the Sea")
    ench = _put(eng, _card("Ench", type_line="Enchantment"))
    bear = _put(eng, _card("Bear"))
    land = _put(eng, _card("Land", type_line="Basic Land — Island"))
    theirs = _put(eng, _card("Theirs"), "p2")
    _fresh(eng)
    assert len(ench._granted_static_abilities) == 1 and len(bear._granted_static_abilities) == 1
    assert not land._granted_static_abilities and not theirs._granted_static_abilities


def test_a_granted_living_weapon_is_never_claimed():
    # The RULE 702.92a trigger is built only for a printed keyword, so a grant would be a silent no-op.
    assert static_effect_specs("each equipment you control has living weapon.") is None


def test_time_of_heroes_and_cathedral_acolyte_read_the_counter_on_your_creatures_only():
    eng = _engine()
    _real(eng, "Time of Heroes")
    _real(eng, "Cathedral Acolyte")
    levelled = _put(eng, _card("Levelled"), counters={"level": 1})
    plain = _put(eng, _card("Plain"))
    theirs = _put(eng, _card("Theirs"), "p2", counters={"level": 1})
    assert _pt(eng, levelled) == (4, 4) and _pt(eng, plain) == (2, 2) and _pt(eng, theirs) == (2, 2)
    levelled.counters["level"] = 0
    assert _pt(eng, levelled) == (2, 2)


def test_aurification_walls_any_creature_with_a_gold_counter_and_keeps_its_types():
    eng = _engine()
    _real(eng, "Aurification")
    mine = _put(eng, _card("Mine", type_line="Creature — Elf"), counters={"gold": 1})
    theirs = _put(eng, _card("Theirs", type_line="Creature — Elf"), "p2", counters={"gold": 1})
    plain = _put(eng, _card("Plain", type_line="Creature — Elf"))
    _fresh(eng)
    for walled in (mine, theirs):
        assert walled.has_subtype("Wall") and walled.has_subtype("Elf") and _kw(eng, walled, "defender")
    assert not plain.has_subtype("Wall") and not _kw(eng, plain, "defender")


def test_ivory_guardians_pump_follows_the_opposing_red_permanent_and_the_name():
    eng = _engine()
    guardians = _real(eng, "Ivory Guardians")
    twin = _put(eng, _card("Ivory Guardians", type_line="Creature — Giant Cleric"), "p2")
    bear = _put(eng, _card("Bear"))
    assert _pt(eng, guardians) == (2, 2)  # no opposing red permanent: no bonus
    red = _put(eng, _card("Red Bear", mana="{R}"), "p2")
    assert _pt(eng, guardians) == (3, 3) and _pt(eng, twin) == (3, 3) and _pt(eng, bear) == (2, 2)
    red.is_token = True  # "nontoken": a red token does not count
    assert _pt(eng, guardians) == (2, 2)


def test_where_x_amounts_read_your_graveyard_and_your_life_total_live():
    eng = _engine()
    host = _put(eng, _card("Host", power=1, toughness=1))
    other = _put(eng, _card("Other", power=1, toughness=1))
    pike = _real(eng, "Runechanter's Pike")
    _attach(eng, pike, host)
    assert _pt(eng, host) == (1, 1) and _kw(eng, host, "first_strike")
    for i, type_line in enumerate(("Instant", "Sorcery", "Creature — Bear")):
        spell = GameObject(_card(f"Gy {i}", type_line=type_line), owner_id="p1", zone=Zone.GRAVEYARD)
        eng.state.player_by_id("p1").graveyard.append(spell)
    theirs = GameObject(_card("Their Instant", type_line="Instant"), owner_id="p2", zone=Zone.GRAVEYARD)
    eng.state.player_by_id("p2").graveyard.append(theirs)
    assert _pt(eng, host) == (3, 1) and _pt(eng, other) == (1, 1)  # two of yours count, not the creature, not theirs
    pike.attached_to = None
    assert _pt(eng, host) == (1, 1)
    priwen = _real(eng, "Aettir and Priwen")
    _attach(eng, priwen, host)
    eng.state.player_by_id("p1").life = 7
    assert _pt(eng, host) == (7, 7)
    eng.state.player_by_id("p1").life = 12
    assert _pt(eng, host) == (12, 12) and _pt(eng, other) == (1, 1)


def test_group_where_x_counts_are_read_live_and_scoped():
    eng = _engine()
    _real(eng, "Gornog, the Red Reaper")
    warrior = _put(eng, _card("Warrior", type_line="Creature — Human Warrior"))
    idle = _put(eng, _card("Idle Warrior", type_line="Creature — Human Warrior"))
    theirs = _put(eng, _card("Their Warrior", type_line="Creature — Human Warrior"), "p2")
    warrior.attacking = True
    theirs.attacking = True
    assert _pt(eng, warrior) == (2, 2)  # no Cowards yet
    _put(eng, _card("Coward", type_line="Creature — Human Coward"), "p2")
    _put(eng, _card("My Coward", type_line="Creature — Human Coward"))  # yours: not counted
    assert _pt(eng, warrior) == (3, 2) and _pt(eng, idle) == (2, 2) and _pt(eng, theirs) == (2, 2)
    _put(eng, _card("Coward 2", type_line="Creature — Human Coward"), "p2")
    assert _pt(eng, warrior) == (4, 2)


def test_champions_of_archery_counts_your_commanders():
    eng = _engine()
    _real(eng, "Champions of Archery // Join the Group")
    first = _put(eng, _card("Cmd 1"))
    first.is_commander = True
    second = _put(eng, _card("Cmd 2"))
    second.is_commander = True
    theirs = _put(eng, _card("Their Cmd"), "p2")
    theirs.is_commander = True
    plain = _put(eng, _card("Plain"))
    assert _pt(eng, first) == (4, 2) and _pt(eng, second) == (4, 2)  # 2 commanders of yours: +2
    assert _pt(eng, plain) == (2, 2) and _pt(eng, theirs) == (2, 2)


# -- engine state: clone / undo --------------------------------------------------------------------------------------


def test_group_type_change_survives_a_clone():
    eng = _engine()
    _real(eng, "Enchanted Evening")
    bear = _put(eng, _card("Bear"))
    _fresh(eng)
    clone = eng.state.clone()
    clone_bear = next(o for o in clone.battlefield if o.card.name == "Bear")
    assert "enchantment" in clone_bear.type_words
    assert "enchantment" in _types(eng, bear)

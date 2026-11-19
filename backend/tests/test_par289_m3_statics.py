"""PAR-289 milestone 3: land-type group scopes, coordinated type lists and the next conditional statics.

Every claimed card binds its real text on a real engine and reads the layer result for the condition true, false and
toggling, plus a same-type bystander outside the subject (RULE 613). Groups: the land-subtype scope fix ("Mountains you
control" are Mountain *lands*, RULE 205.3i, not creatures, RULE 205.3m) and the coordinated type lists ("Treefolk and
Forests you control", "Mounts and Vehicles you control", "Goblins you control and Elementals you control"); the gated
self-animation ("~ is a 5/5 Golem artifact creature as long as ..."); exact counter / Aura / Equipment counts; the
"exactly one creature" gate; "each land gets +2/+2 as long as it's a creature"; "All Mountains are Plains";
"creatures with flying your opponents control get -1/-0"; Angelic Voices' comma-bearing trailing condition and Jetmir's
"also get".
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_condition, static_effect_specs
from mtg_analyzer.parser.oracle.catalogue.static_rows.self_statics import conditional_static_specs
from mtg_analyzer.parser.oracle.gate import parse_oracle

#: (name, type line, oracle text) of every card this milestone newly models.
CLAIMED = [
    ('Angelic Voices', 'Enchantment', 'Creatures you control get +1/+1 as long as you control no nonartifact, nonwhite creatures.'),
    ('Brass Knuckles', 'Artifact — Equipment', 'When you cast this spell, copy it. (The copy becomes a token.)\nEquipped creature has double strike as long as two or more Equipment are attached to it.\nEquip {1} ({1}: Attach to target creature you control. Equip only as a sorcery.)'),
    ('Caterwauling Boggart', 'Creature — Goblin Shaman', "Goblins you control and Elementals you control have menace. (They can't be blocked except by two or more creatures.)"),
    ('Cloudspire Captain', 'Creature — Human Pilot', 'Mounts and Vehicles you control get +1/+1.\nThis creature saddles Mounts and crews Vehicles as though its power were 2 greater.'),
    ('Conversion', 'Enchantment', 'At the beginning of your upkeep, sacrifice this enchantment unless you pay {W}{W}.\nAll Mountains are Plains.'),
    ('Deadly Wanderings', 'Enchantment', 'As long as you control exactly one creature, that creature gets +2/+0 and has deathtouch and lifelink.'),
    ('Earth Surge', 'Enchantment', "Each land gets +2/+2 as long as it's a creature."),
    ('Glaciers', 'Enchantment', 'At the beginning of your upkeep, sacrifice this enchantment unless you pay {W}{U}.\nAll Mountains are Plains.'),
    ('Grond, the Gatebreaker', 'Legendary Artifact — Vehicle', "Trample\nAs long as it's your turn and you control an Army, Grond is an artifact creature.\nCrew 3 (Tap any number of creatures you control with total power 3 or more: This Vehicle becomes an artifact creature until end of turn.)"),
    ('Homarid', 'Creature — Homarid', 'This creature enters with a tide counter on it.\nAt the beginning of your upkeep, put a tide counter on this creature.\nAs long as there is exactly one tide counter on this creature, it gets -1/-1.\nAs long as there are exactly three tide counters on this creature, it gets +1/+1.\nWhenever there are four or more tide counters on this creature, remove all tide counters from it.'),
    ('Homicidal Seclusion', 'Enchantment', 'As long as you control exactly one creature, that creature gets +3/+1 and has lifelink.'),
    ('Jetmir, Nexus of Revels', 'Legendary Creature — Cat Demon', 'Creatures you control get +1/+0 and have vigilance as long as you control three or more creatures.\nCreatures you control also get +1/+0 and have trample as long as you control six or more creatures.\nCreatures you control also get +1/+0 and have double strike as long as you control nine or more creatures.'),
    ('Miriam, Herd Whisperer', 'Legendary Creature — Human Druid', 'During your turn, Mounts and Vehicles you control have hexproof.\nWhenever a Mount or Vehicle you control attacks, put a +1/+1 counter on it.'),
    ('One-Eyed Scarecrow', 'Artifact Creature — Scarecrow', 'Defender\nCreatures with flying your opponents control get -1/-0.'),
    ('Phoenix Fleet Airship', 'Artifact — Vehicle', "Flying\nAt the beginning of your end step, if you sacrificed a permanent this turn, create a token that's a copy of this Vehicle.\nAs long as you control eight or more permanents named Phoenix Fleet Airship, this Vehicle is an artifact creature.\nCrew 1"),
    ('Rusted Relic', 'Artifact', 'Metalcraft — This artifact is a 5/5 Golem artifact creature as long as you control three or more artifacts.'),
    ('Smog Elemental', 'Creature — Elemental', 'Flying\nCreatures with flying your opponents control get -1/-1.'),
    ('Timber Paladin', 'Artifact Creature — Knight', 'As long as this creature is enchanted by exactly one Aura, it has base power and toughness 3/3.\nAs long as this creature is enchanted by exactly two Auras, it has base power and toughness 5/5 and vigilance.\nAs long as this creature is enchanted by three or more Auras, it has base power and toughness 10/10, vigilance, and trample.'),
    ('Timber Protector', 'Creature — Treefolk Warrior', 'Other Treefolk creatures you control get +1/+1.\nOther Treefolk and Forests you control have indestructible.'),
    ('War Balloon', 'Artifact — Vehicle', "Flying\n{1}: Put a fire counter on this Vehicle.\nAs long as this Vehicle has three or more fire counters on it, it's an artifact creature.\nCrew 3 (Tap any number of creatures you control with total power 3 or more: This Vehicle becomes an artifact creature until end of turn.)"),

]


@pytest.mark.parametrize("name,type_line,text", CLAIMED, ids=[c[0] for c in CLAIMED])
def test_claimed_real_cards_parse_modeled(name, type_line, text):
    creature = "Creature" in type_line
    # Scryfall lists an ability-word label ("Metalcraft —") among the keywords; the normaliser strips it by that signal.
    keywords = ["Metalcraft"] if text.startswith("Metalcraft") else []
    card = Card(id=name, name=name, oracle_text=text, type_line=type_line, is_creature=creature,
                power=1 if creature else None, toughness=1 if creature else None, keywords=keywords)
    assert parse_oracle(card).modeled


@pytest.mark.parametrize("clause", [
    "goblins you control and elementals have menace.",                    # the controller phrase must close the list
    "forests and zzzzz you control have haste.",                          # a non-type word is never guessed
    "all mountains are mountains.",
    "all mountains are zzzzz.",
    "all zzzzz are plains.",
    "each zzzzz gets +1/+1 as long as it's a creature.",
    "each land gets +1/+1 as long as it's a planeswalker.",
    "creatures with zzzzz your opponents control get -1/-0.",
    "~ is a 5/5 zzzzz artifact creature as long as you control three or more artifacts.",
])
def test_unreadable_shapes_fail_closed(clause):
    assert static_effect_specs(clause) is None and conditional_static_specs(clause) is None


@pytest.mark.parametrize("phrase", [
    "there are exactly zzzzz tide counters on ~",
    "~ is enchanted by exactly zzzzz auras",
    "zzzzz equipment are attached to it",
])
def test_unknown_condition_phrases_fail_closed(phrase):
    assert static_condition(phrase) is None


# -- engine harness --------------------------------------------------------------------------------------------------


def _card(name, text="", type_line="Creature — Bear", power=2, toughness=2, mana=""):
    creature = "Creature" in type_line
    return Card(id=name, name=name, oracle_text=text, type_line=type_line, is_creature=creature,
                power=power if creature else None, toughness=toughness if creature else None,
                mana_cost_string=mana)


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


def _real(eng, row, controller="p1", counters=None):
    name, type_line, text = row
    card = _card(name, text, type_line)
    if text.startswith("Metalcraft"):
        card.keywords = ["Metalcraft"]
    return _put(eng, card, controller, counters)


def _row(name):
    return next(r for r in CLAIMED if r[0] == name)


def _pt(eng, obj):
    eng.recompute_continuous_effects()
    return obj.power, obj.toughness


def _has(eng, obj, keyword):
    eng.recompute_continuous_effects()
    return keyword in obj.granted_keywords


def _is_creature(eng, obj):
    eng.recompute_continuous_effects()
    return obj.is_creature


def _land(name, subtype):
    return _card(name, type_line=f"Basic Land — {subtype}")


# -- the land-subtype scope fix and the coordinated lists -------------------------------------------------------------

#: The two already-MODELED cards the old scope reading corrupted: an emblem granting to "Mountains"/"Islands you control".
LAND_EMBLEM_CARDS = [
    ('Koth of the Hammer', 'Legendary Planeswalker — Koth', '+1: Untap target Mountain. It becomes a 4/4 red Elemental creature until end of turn. It\'s still a land.\n−2: Add {R} for each Mountain you control.\n−5: You get an emblem with "Mountains you control have \'{T}: This land deals 1 damage to any target.\'"', "Mountain"),
    ('Mu Yanling, Sky Dancer', 'Legendary Planeswalker — Yanling', '+2: Until your next turn, up to one target creature gets -2/-0 and loses flying.\n−3: Create a 4/4 blue Elemental Bird creature token with flying.\n−8: You get an emblem with "Islands you control have \'{T}: Draw a card.\'"', "Island"),
]


def test_land_subtype_scope_is_lands_not_creatures():
    specs = static_effect_specs("forests you control have vigilance.")
    assert specs[0].params["affects"]["filter"] == {"card_type": "land", "subtype": "Forest"}
    specs = static_effect_specs("plains you control get +1/+1.")
    assert specs[0].params["affects"]["filter"] == {"card_type": "land", "subtype": "Plains"}
    # A creature type word keeps the creature scope.
    assert static_effect_specs("goblins you control have haste.")[0].params["affects"]["filter"] == {
        "card_type": "creature", "subtype": "Goblin"}


@pytest.mark.parametrize("name,type_line,text,word", LAND_EMBLEM_CARDS, ids=[c[0] for c in LAND_EMBLEM_CARDS])
def test_emblem_cards_scope_their_grant_to_land_subtypes(name, type_line, text, word):
    # RULE 205.3i: the emblem's group is the Mountain / Island *lands*; the old reading made it creatures of that type
    # (so the emblem granted nothing to an ordinary land).
    result = parse_oracle(Card(id=name, name=name, oracle_text=text, type_line=type_line, loyalty=4))
    assert result.modeled
    filters = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("subtype") == word:
                filters.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for spec in result.specs:
        walk(spec.to_dict())
    assert {"card_type": "land", "subtype": word} in filters
    assert not any(f.get("card_type") == "creature" for f in filters)


@pytest.mark.parametrize("emblem_text,word", [
    ('You get an emblem with "Mountains you control have \'{T}: This land deals 1 damage to any target.\'"', "Mountain"),
    ('You get an emblem with "Islands you control have \'{T}: Draw a card.\'"', "Island"),
])
def test_real_emblem_grants_to_ordinary_lands_of_the_type(emblem_text, word):
    # Koth of the Hammer's -5 and Mu Yanling's -8 emblem lines, resolved for real: before the fix the grant needed the
    # land to be a *creature* of that type, so an ordinary Mountain/Island never got the ability.
    from mtg_analyzer.game.binding.core import attach_to_object

    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    spell = Card(id="Emblem Source", name="Emblem Source", type_line="Sorcery", oracle_text=emblem_text,
                 mana_cost_string="{1}{W}", converted_mana_cost=2, is_sorcery=True)
    result = parse_oracle(spell)
    assert result.modeled
    obj = GameObject(spell, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, result.specs)
    p1.hand.append(obj)
    p1.mana_pool.add_many({"W": 5})
    eng.state.current_step = "main1"
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()
    assert len(p1.emblems) == 1
    typed = _put(eng, _land(word, word))
    other = _put(eng, _land("Other", "Plains" if word != "Plains" else "Forest"))
    theirs = _put(eng, _land("Their " + word, word), "p2")
    creature = _put(eng, _card(word + " Bear", type_line="Creature — Bear"))
    eng.recompute_continuous_effects()
    assert typed._granted_activated_abilities or typed._granted_mana_abilities
    assert not other._granted_activated_abilities and not theirs._granted_activated_abilities
    assert not creature._granted_activated_abilities


def test_land_group_grant_reaches_only_your_lands_of_the_type():
    eng = _engine()
    text = 'Mountains you control have "{T}: This land deals 1 damage to any target."'
    stand_in = _put(eng, _card("Emblem stand-in", text, "Enchantment"))
    mountain = _put(eng, _land("Mountain", "Mountain"))
    forest = _put(eng, _land("Forest", "Forest"))
    theirs = _put(eng, _land("Their Mountain", "Mountain"), "p2")
    bear = _put(eng, _card("Mountain Bear", type_line="Creature — Bear"))  # shares the word, is no Mountain land
    eng.recompute_continuous_effects()
    assert mountain._granted_activated_abilities
    assert not forest._granted_activated_abilities and not theirs._granted_activated_abilities
    assert not bear._granted_activated_abilities
    eng.state.battlefield.remove(stand_in)
    eng.recompute_continuous_effects()
    assert not mountain._granted_activated_abilities  # the source left: the static stops


def test_timber_protector_union_group_is_treefolk_creatures_and_forest_lands_you_control():
    eng = _engine()
    protector = _real(eng, _row("Timber Protector"))
    protector.card.type_line = "Creature — Treefolk Warrior"
    ent = _put(eng, _card("Ent", type_line="Creature — Treefolk"))
    forest = _put(eng, _land("Forest", "Forest"))
    mountain = _put(eng, _land("Mountain", "Mountain"))
    bear = _put(eng, _card("Bear"))
    their_forest = _put(eng, _land("Their Forest", "Forest"), "p2")
    their_ent = _put(eng, _card("Their Ent", type_line="Creature — Treefolk"), "p2")
    assert _has(eng, ent, "indestructible") and _has(eng, forest, "indestructible")
    assert not _has(eng, protector, "indestructible")  # RULE 109.5: "other" excludes the source
    assert not _has(eng, mountain, "indestructible") and not _has(eng, bear, "indestructible")
    assert not _has(eng, their_forest, "indestructible") and not _has(eng, their_ent, "indestructible")  # "you control"
    assert _pt(eng, ent) == (3, 3)  # the card's own "Other Treefolk creatures you control get +1/+1" still applies
    eng.state.battlefield.remove(protector)
    assert not _has(eng, ent, "indestructible") and not _has(eng, forest, "indestructible")


def test_caterwauling_boggart_two_tribes_you_control_only():
    eng = _engine()
    _real(eng, _row("Caterwauling Boggart"))
    goblin = _put(eng, _card("Goblin", type_line="Creature — Goblin"))
    elemental = _put(eng, _card("Elemental", type_line="Creature — Elemental"))
    bear = _put(eng, _card("Bear"))
    theirs = _put(eng, _card("Their Goblin", type_line="Creature — Goblin"), "p2")
    assert _has(eng, goblin, "menace") and _has(eng, elemental, "menace")
    assert not _has(eng, bear, "menace") and not _has(eng, theirs, "menace")


def test_cloudspire_captain_mounts_and_vehicles_you_control_get_the_bonus():
    eng = _engine()
    _real(eng, _row("Cloudspire Captain"))
    mount = _put(eng, _card("Mount", type_line="Creature — Mount"))
    vehicle = _put(eng, _card("Crewed Vehicle", type_line="Artifact Creature — Vehicle"))
    bear = _put(eng, _card("Bear"))
    their_mount = _put(eng, _card("Their Mount", type_line="Creature — Mount"), "p2")
    land = _put(eng, _land("Forest", "Forest"))
    assert _pt(eng, mount) == (3, 3) and _pt(eng, vehicle) == (3, 3)
    assert _pt(eng, bear) == (2, 2) and _pt(eng, their_mount) == (2, 2)
    assert not _is_creature(eng, land)


def test_miriam_gives_mounts_and_vehicles_hexproof_on_your_turn_only():
    eng = _engine()
    _real(eng, _row("Miriam, Herd Whisperer"))
    mount = _put(eng, _card("Mount", type_line="Creature — Mount"))
    bear = _put(eng, _card("Bear"))
    assert eng.state.active_player.id == "p1"
    assert _has(eng, mount, "hexproof") and not _has(eng, bear, "hexproof")
    eng.state.active_player_index = 1  # opponent's turn: the "during your turn" gate closes
    assert not _has(eng, mount, "hexproof")


# -- the gated self-animation ------------------------------------------------------------------------------------------


def test_rusted_relic_is_a_golem_creature_only_with_three_artifacts():
    eng = _engine()
    relic = _real(eng, _row("Rusted Relic"))
    assert not _is_creature(eng, relic)
    a1 = _put(eng, _card("Art 1", type_line="Artifact"))
    assert not _is_creature(eng, relic)
    a2 = _put(eng, _card("Art 2", type_line="Artifact"))
    assert _is_creature(eng, relic) and _pt(eng, relic) == (5, 5)
    assert continuous.has_subtype(relic, "Golem")
    eng.state.battlefield.remove(a2)  # the condition ends: it stops being a creature
    assert not _is_creature(eng, relic)
    _put(eng, _card("Art 3", type_line="Artifact"), "p2")  # an opponent's artifact does not count
    assert not _is_creature(eng, relic)
    del a1


def test_war_balloon_animates_at_three_fire_counters_and_toggles():
    eng = _engine()
    balloon = _real(eng, _row("War Balloon"), counters={"fire": 2})
    assert not _is_creature(eng, balloon)
    balloon.counters["fire"] = 3
    assert _is_creature(eng, balloon)
    balloon.counters["fire"] = 2
    assert not _is_creature(eng, balloon)


def test_phoenix_fleet_airship_needs_eight_permanents_with_its_name():
    eng = _engine()
    ship = _real(eng, _row("Phoenix Fleet Airship"))
    for _ in range(6):
        _real(eng, _row("Phoenix Fleet Airship"))
    assert not _is_creature(eng, ship)  # seven
    _real(eng, _row("Phoenix Fleet Airship"))
    assert _is_creature(eng, ship)  # eight
    _real(eng, _row("Phoenix Fleet Airship"), "p2")  # an opponent's copy is not "you control"
    other = _put(eng, _card("Other Vehicle", type_line="Artifact — Vehicle"))
    assert not _is_creature(eng, other)


def test_grond_is_a_creature_on_your_turn_while_you_control_an_army():
    eng = _engine()
    grond = _real(eng, _row("Grond, the Gatebreaker"))
    assert not _is_creature(eng, grond)
    army = _put(eng, _card("Army", type_line="Creature — Army"))
    assert _is_creature(eng, grond)
    eng.state.active_player_index = 1
    assert not _is_creature(eng, grond)  # not your turn
    eng.state.active_player_index = 0
    eng.state.battlefield.remove(army)
    assert not _is_creature(eng, grond)


# -- counts: counters, Auras, Equipment, creatures ----------------------------------------------------------------------


def test_homarid_exact_tide_counter_counts():
    eng = _engine()
    homarid = _real(eng, _row("Homarid"), counters={"tide": 1})
    twin = _put(eng, _card("Twin"))
    assert _pt(eng, homarid) == (1, 1) and _pt(eng, twin) == (2, 2)
    homarid.counters["tide"] = 2
    assert _pt(eng, homarid) == (2, 2)  # neither "exactly one" nor "exactly three"
    homarid.counters["tide"] = 3
    assert _pt(eng, homarid) == (3, 3)
    homarid.counters["tide"] = 4
    assert _pt(eng, homarid) == (2, 2)


def _enchant(eng, host, n):
    for i in range(n):
        aura = _put(eng, _card(f"Aura {i}", "Enchant creature", "Enchantment — Aura"))
        aura.attached_to = host.instance_id


def test_timber_paladin_bases_by_exact_aura_count():
    eng = _engine()
    paladin = _real(eng, _row("Timber Paladin"))
    paladin.card.power, paladin.card.toughness = 1, 1
    bystander = _put(eng, _card("Bystander"))
    assert _pt(eng, paladin) == (1, 1)
    _enchant(eng, paladin, 1)
    assert _pt(eng, paladin) == (3, 3) and not _has(eng, paladin, "vigilance")
    _enchant(eng, paladin, 1)
    assert _pt(eng, paladin) == (5, 5) and _has(eng, paladin, "vigilance") and not _has(eng, paladin, "trample")
    _enchant(eng, paladin, 1)
    assert _pt(eng, paladin) == (10, 10) and _has(eng, paladin, "trample")
    _enchant(eng, bystander, 3)  # Auras on another creature do not count
    assert _pt(eng, bystander) == (2, 2)


def test_exactly_one_aura_gate_is_an_upper_bound_too():
    eng = _engine()
    text = "As long as this creature is enchanted by exactly one Aura, it has base power and toughness 3/3."
    lone = _put(eng, _card("Lone Paladin", text, "Creature — Knight", power=1, toughness=1))
    assert _pt(eng, lone) == (1, 1)
    _enchant(eng, lone, 1)
    assert _pt(eng, lone) == (3, 3)
    _enchant(eng, lone, 1)
    assert _pt(eng, lone) == (1, 1)  # two Auras: "exactly one" no longer holds, nothing else sets the base


def test_brass_knuckles_double_strike_needs_two_equipment_on_the_creature():
    eng = _engine()
    knuckles = _real(eng, _row("Brass Knuckles"))
    host = _put(eng, _card("Host"))
    other = _put(eng, _card("Other"))
    knuckles.attached_to = host.instance_id
    assert not _has(eng, host, "double_strike")  # one Equipment
    sword = _put(eng, _card("Sword", "", "Artifact — Equipment"))
    sword.attached_to = other.instance_id
    assert not _has(eng, host, "double_strike") and not _has(eng, other, "double_strike")  # one each
    sword.attached_to = host.instance_id
    assert _has(eng, host, "double_strike") and not _has(eng, other, "double_strike")
    sword.attached_to = None
    assert not _has(eng, host, "double_strike")


def test_angelic_voices_off_when_a_nonartifact_nonwhite_creature_is_on_your_side():
    eng = _engine()
    _real(eng, _row("Angelic Voices"))
    angel = _put(eng, _card("Angel", mana="{W}"))
    golem = _put(eng, _card("Golem", type_line="Artifact Creature — Golem"))
    assert _pt(eng, angel) == (3, 3) and _pt(eng, golem) == (3, 3)
    green = _put(eng, _card("Green Bear", mana="{G}"))
    assert _pt(eng, angel) == (2, 2) and _pt(eng, green) == (2, 2)
    eng.state.battlefield.remove(green)
    _put(eng, _card("Their Bear", mana="{G}"), "p2")  # an opponent's creature does not switch it off
    assert _pt(eng, angel) == (3, 3)


@pytest.mark.parametrize("name", ["Deadly Wanderings", "Homicidal Seclusion"])
def test_exactly_one_creature_gate(name):
    eng = _engine()
    _real(eng, _row(name))
    only = _put(eng, _card("Only"))
    theirs = _put(eng, _card("Theirs"), "p2")
    boosted = _pt(eng, only)
    assert boosted[0] > 2  # the one creature is buffed
    assert _pt(eng, theirs) == (2, 2)  # an opponent's creature is neither counted nor buffed
    second = _put(eng, _card("Second"))
    assert _pt(eng, only) == (2, 2) and _pt(eng, second) == (2, 2)  # two creatures: the gate is closed
    eng.state.battlefield.remove(second)
    assert _pt(eng, only) == boosted


def test_jetmir_tiers_stack_by_creature_count():
    eng = _engine()
    jetmir = _real(eng, _row("Jetmir, Nexus of Revels"))
    bears = [_put(eng, _card(f"Bear {i}")) for i in range(2)]
    assert _pt(eng, jetmir) == (3, 2) and _has(eng, jetmir, "vigilance")  # three creatures: +1/+0
    assert not _has(eng, jetmir, "trample")
    bears += [_put(eng, _card(f"Bear {i}")) for i in range(2, 5)]
    assert _pt(eng, jetmir) == (4, 2) and _has(eng, jetmir, "trample")  # six: +2/+0
    bears += [_put(eng, _card(f"Bear {i}")) for i in range(5, 8)]
    assert _pt(eng, jetmir) == (5, 2) and _has(eng, jetmir, "double_strike")  # nine: +3/+0
    theirs = _put(eng, _card("Theirs"), "p2")
    assert _pt(eng, theirs) == (2, 2)
    eng.state.battlefield.remove(bears[0])
    assert not _has(eng, jetmir, "double_strike")


# -- group subjects -----------------------------------------------------------------------------------------------------


def test_earth_surge_pumps_only_lands_that_are_creatures():
    eng = _engine()
    _real(eng, _row("Earth Surge"))
    animated = _put(eng, _card("Animated", type_line="Land Creature — Forest", power=1, toughness=1))
    theirs = _put(eng, _card("Their Animated", type_line="Land Creature — Forest", power=1, toughness=1), "p2")
    plain_land = _put(eng, _land("Forest", "Forest"))
    bear = _put(eng, _card("Bear"))
    assert _pt(eng, animated) == (3, 3) and _pt(eng, theirs) == (3, 3)  # global
    assert _pt(eng, bear) == (2, 2)
    assert not _is_creature(eng, plain_land)
    assert plain_land.power in (None, 0)


def test_conversion_turns_every_mountain_into_a_plains_and_nothing_else():
    eng = _engine()
    _real(eng, _row("Conversion"))
    mountain = _put(eng, _land("Mountain", "Mountain"))
    theirs = _put(eng, _land("Their Mountain", "Mountain"), "p2")
    forest = _put(eng, _land("Forest", "Forest"))
    eng.recompute_continuous_effects()

    def subtypes(obj):
        return {t.lower() for t in continuous.derived_subtype_words(obj)}

    assert "plains" in subtypes(mountain) and "mountain" not in subtypes(mountain)  # RULE 305.7: replaced, not added
    assert "plains" in subtypes(theirs)  # every player's Mountains
    assert subtypes(forest) == {"forest"}


def test_opponents_flying_creatures_get_the_penalty_only():
    eng = _engine()
    _real(eng, _row("Smog Elemental"))
    flyer = _put(eng, _card("Their Flyer", "Flying", "Creature — Bird"), "p2")
    ground = _put(eng, _card("Their Bear"), "p2")
    mine = _put(eng, _card("My Flyer", "Flying", "Creature — Bird"))
    assert _pt(eng, flyer) == (1, 1) and _pt(eng, ground) == (2, 2) and _pt(eng, mine) == (2, 2)
    eng.state.battlefield.remove(next(o for o in eng.state.battlefield if o.card.name == "Smog Elemental"))
    assert _pt(eng, flyer) == (2, 2)

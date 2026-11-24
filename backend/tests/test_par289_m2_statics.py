"""PAR-289 milestone 2: group subjects, host conditions and Aura statements for continuous statics.

Every claimed group binds the real card text on a real engine and reads the layer result for the condition true,
false and toggling, plus a same-type bystander outside the subject (RULE 613). Groups: "each [other] creature you
control with a <counter> counter on it has <keyword>"; the "each creature that's a <type list> gets/has" subject and
"other legendary permanents you control"; the host / self condition phrases (isn't attacking or blocking, life total
vs starting life total, you control enchanted creature, enchanted creature is legendary / red or green / not
legendary); the self "has <keyword> and is a <type> in addition to its other types"; and the A3 Aura statements
(creature-type statement with a base P/T, card-type replacement, colourless type with a granted ability, supertype).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_condition, static_effect_specs
from mtg_analyzer.parser.oracle.gate import parse_oracle

#: (name, type line, oracle text) of every card this milestone newly models or now models fully.
# BUG-75: Unleash and Companion have no engine behaviour, so Exava's and Kaheera's keyword lines are not part of the text below.
CLAIMED = [
    ('Aerial Modification', 'Enchantment — Aura', "Enchant creature or Vehicle\nAs long as enchanted permanent is a Vehicle, it's a creature in addition to its other types.\nEnchanted creature gets +2/+2 and has flying."),
    ("Avacyn's Memorial", 'Legendary Artifact', 'Indestructible\nOther legendary permanents you control have indestructible.'),
    ('Awakened Awareness', 'Enchantment — Aura', 'Enchant artifact or creature\nWhen this Aura enters, put X +1/+1 counters on enchanted permanent.\nAs long as enchanted permanent is a creature, it has base power and toughness 1/1.'),
    ('Bladed Bracers', 'Artifact — Equipment', 'Equipped creature gets +1/+1.\nAs long as equipped creature is a Human or an Angel, it has vigilance.\nEquip {2} ({2}: Attach to target creature you control. Equip only as a sorcery.)'),
    ('Bushmaster, Coiled Henchman', 'Legendary Creature — Snake Human Villain', 'Deathtouch\nEach other creature you control with a +1/+1 counter on it has deathtouch.'),
    ('Combat Research', 'Enchantment — Aura', 'Enchant creature\nEnchanted creature has "Whenever this creature deals combat damage to a player, draw a card."\nAs long as enchanted creature is legendary, it gets +1/+1 and has ward {1}. (Whenever enchanted creature becomes the target of a spell or ability an opponent controls, counter it unless that player pays {1}.)'),
    ('Enchantmentize', 'Enchantment — Aura', "Enchant creature or enchantment\nEnchanted permanent is an enchantment and loses all other card types. (It still has its abilities, but it's no longer a creature.)"),
    ('Essence Leak', 'Enchantment — Aura', 'Enchant permanent\nAs long as enchanted permanent is red or green, it has "At the beginning of your upkeep, sacrifice this permanent unless you pay its mana cost."'),
    ('Exava, Rakdos Blood Witch', 'Legendary Creature — Human Cleric', "First strike, haste\nEach other creature you control with a +1/+1 counter on it has haste."),
    ('Ezio, Brash Novice', 'Legendary Creature — Human', 'Whenever Ezio attacks, put a +1/+1 counter on it.\nAs long as Ezio has two or more counters on it, it has first strike and is an Assassin in addition to its other types.'),
    ('Gallia, the Merrymaker', 'Legendary Creature — Satyr', 'Haste\nEach other creature you control with a +1/+1 counter on it has haste.\n{1}{R}, {T}: Put a +1/+1 counter on target creature that entered this turn.'),
    ("Gimli's Axe", 'Artifact — Equipment', "Equipped creature gets +3/+0.\nAs long as equipped creature is legendary, it has menace. (It can't be blocked except by two or more creatures.)\nEquip {2} ({2}: Attach to target creature you control. Equip only as a sorcery.)"),
    ('Howlpack Resurgence', 'Enchantment', "Flash\nEach creature you control that's a Wolf or a Werewolf gets +1/+1 and has trample."),
    ('Imprisoned in the Moon', 'Enchantment — Aura', 'Enchant creature, land, or planeswalker\nEnchanted permanent is a colorless land with "{T}: Add {C}" and loses all other card types and abilities.'),
    ("In Bolas's Clutches", 'Legendary Enchantment — Aura', 'Enchant permanent\nYou control enchanted permanent.\nEnchanted permanent is legendary.'),
    ('In Too Deep', 'Enchantment — Aura', 'Split second (As long as this spell is on the stack, players can\'t cast spells or activate abilities that aren\'t mana abilities.)\nEnchant creature, planeswalker, or Clue\nEnchanted permanent is a colorless Clue artifact with "{2}, Sacrifice this artifact: Draw a card" and loses all other abilities. (It\'s no longer a creature or planeswalker.)'),
    ('Intrepid Ace', 'Creature — Human Pilot', "This creature gets +2/+0 as long as it isn't attacking or blocking."),
    ('Kaheera, the Orphanguard', 'Legendary Creature — Cat Beast', "Vigilance\nEach other creature you control that's a Cat, Elemental, Nightmare, Dinosaur, or Beast gets +1/+1 and has vigilance."),
    ('Kindred Boon', 'Enchantment', 'As this enchantment enters, choose a creature type.\n{1}{W}: Put a divinity counter on target creature you control of the chosen type.\nEach creature you control with a divinity counter on it has indestructible.'),
    ('Lovisa Coldeyes', 'Legendary Creature — Human', "Each creature that's a Barbarian, a Warrior, or a Berserker gets +2/+2 and has haste."),
    ("Mishra's Domination", 'Enchantment — Aura', "Enchant creature\nAs long as you control enchanted creature, it gets +2/+2. Otherwise, it can't block."),
    ('Namor, Scourge of the Seas', 'Legendary Creature — Mutant Merfolk Villain', 'Flying\nEach other Merfolk you control with a +1/+1 counter on it has flying.\nAt the beginning of combat on your turn, target creature you control connives. (Draw a card, then discard a card. If you discarded a nonland card, put a +1/+1 counter on that creature.)'),
    ('One with the Stars', 'Enchantment — Aura', "Enchant creature or enchantment\nEnchanted permanent is an enchantment and loses all other card types. (It still has its abilities, but it's no longer a creature.)"),
    ('Oni Possession', 'Enchantment — Aura', 'Enchant creature\nAt the beginning of your upkeep, sacrifice a creature.\nEnchanted creature gets +3/+3 and has trample.\nEnchanted creature is a Demon Spirit.'),
    ('Path of Bravery', 'Enchantment', 'As long as your life total is greater than or equal to your starting life total, creatures you control get +1/+1.\nWhenever one or more creatures you control attack, you gain life equal to the number of attacking creatures.'),
    ('Siege Modification', 'Enchantment — Aura', "Enchant creature or Vehicle\nAs long as enchanted permanent is a Vehicle, it's a creature in addition to its other types.\nEnchanted creature gets +3/+0 and has first strike."),
    ('Skeleton Crew', 'Creature — Skeleton Pirate', "Each other creature you control that's a Skeleton or Pirate gets +1/+1.\nWhenever one or more creature cards leave your graveyard, create a 2/2 black Skeleton Pirate creature token. (This ability triggers only from the battlefield.)\n{5}{B}: Return this card from your graveyard to the battlefield tapped."),
    ('Skyknight Squire', 'Creature — Cat Scout', 'Whenever another creature you control enters, put a +1/+1 counter on this creature.\nAs long as this creature has three or more +1/+1 counters on it, it has flying and is a Knight in addition to its other types.'),
    ('Song of the Dryads', 'Enchantment — Aura', 'Enchant permanent\nEnchanted permanent is a colorless Forest land.'),
    ('Sporecrown Thallid', 'Creature — Fungus', "Each other creature you control that's a Fungus or Saproling gets +1/+1."),
    ('Sugar Coat', 'Enchantment — Aura', 'Flash\nEnchant creature or Food\nEnchanted permanent is a colorless Food artifact with "{2}, {T}, Sacrifice this artifact: You gain 3 life" and loses all other card types and abilities.'),
    ('Weatherlight Compleated', 'Legendary Artifact — Vehicle', "Flying\nAs long as Weatherlight Compleated has four or more phyresis counters on it, it's a Phyrexian creature in addition to its other types.\nWhenever a creature you control dies, put a phyresis counter on Weatherlight Compleated. Then draw a card if it has seven or more phyresis counters on it. If it doesn't, scry 1."),
    ("Champion's Helm", 'Artifact — Equipment', "Equipped creature gets +2/+2.\nAs long as equipped creature is legendary, it has hexproof. (It can't be the target of spells or abilities your opponents control.)\nEquip {1}"),
    ('De-evolve', 'Enchantment — Aura', "Enchant creature\nEnchanted creature gets -4/-0, can't block, and is a Salamander. (It loses all other creature types.)\nThreshold — At the beginning of each upkeep, if there are seven or more cards in your graveyard, exile enchanted creature."),
    ("Hero's Heirloom", 'Artifact — Equipment', 'Equipped creature gets +2/+1.\nAs long as equipped creature is legendary, it has trample and haste.\nEquip {2}'),
]


@pytest.mark.parametrize("name,type_line,text", CLAIMED, ids=[c[0] for c in CLAIMED])
def test_claimed_real_cards_parse_modeled(name, type_line, text):
    creature = "Creature" in type_line
    card = Card(id=name, name=name, oracle_text=text, type_line=type_line, is_creature=creature,
                power=1 if creature else None, toughness=1 if creature else None)
    assert parse_oracle(card).modeled


@pytest.mark.parametrize("clause", [
    "each creature that's a zzzzz gets +1/+1.",                                  # not a subtype word
    "each creature you control that's a wolf or a zzzzz gets +1/+1 and has trample.",
    "each creature you control that's a wolf gets +1/+1 and has ward {1}.",     # parametric grant stays closed
    "each creature you control with a divinity counter on it has hexproof from red.",
    "enchanted creature is a zzzzz with base power and toughness 1/1.",
    "enchanted creature is a colorless forest artifact.",                        # Forest is no artifact subtype
    "enchanted permanent is a colorless clue artifact with \"zzz blah\" and loses all other abilities.",
    "enchanted permanent is a treasure.",                                        # no card type named
    "other legendary permanents you control have flanking x.",
])
def test_unreadable_subjects_fail_closed(clause):
    assert static_effect_specs(clause) is None


@pytest.mark.parametrize("phrase", [
    "it isn't attacking",
    "your life total is greater than your starting life total plus one",
    "you control enchanted zzzz",
    "enchanted creature isn't zzzz",
])
def test_unknown_condition_phrases_fail_closed(phrase):
    assert static_condition(phrase) is None


# -- engine harness --------------------------------------------------------------------------------------------------


def _card(name, text="", type_line="Creature — Bear", power=2, toughness=2, mana="", legendary=False):
    creature = "Creature" in type_line
    if legendary:
        type_line = "Legendary " + type_line
    return Card(id=name, name=name, oracle_text=text, type_line=type_line, is_creature=creature,
                power=power if creature else None, toughness=toughness if creature else None, mana_cost_string=mana)


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


def _aura(eng, name, text, host, controller="p1"):
    aura = _put(eng, _card(name, text, "Enchantment — Aura"), controller)
    aura.attached_to = host.instance_id
    return aura


def _pt(eng, obj):
    eng.recompute_continuous_effects()
    return obj.power, obj.toughness


def _has(eng, obj, keyword):
    eng.recompute_continuous_effects()
    return keyword in obj.granted_keywords


# -- F1: counters on the subject -------------------------------------------------------------------------------------

EXAVA = "Each other creature you control with a +1/+1 counter on it has haste."


def test_each_other_creature_with_a_counter_is_yours_only_and_toggles():
    eng = _engine()
    exava = _put(eng, _card("Exava, Rakdos Blood Witch", EXAVA, "Legendary Creature — Vampire"), counters={"+1/+1": 1})
    with_counter = _put(eng, _card("With"), counters={"+1/+1": 1})
    without = _put(eng, _card("Without"))
    other_kind = _put(eng, _card("Other kind"), counters={"time": 2})
    theirs = _put(eng, _card("Theirs"), "p2", counters={"+1/+1": 1})
    assert _has(eng, with_counter, "haste")
    assert not _has(eng, exava, "haste")  # RULE 109.5: "other" excludes the source, even with a counter itself
    assert not _has(eng, without, "haste") and not _has(eng, other_kind, "haste")
    assert not _has(eng, theirs, "haste")  # "you control"
    with_counter.counters.clear()
    assert not _has(eng, with_counter, "haste")  # the counter went away: the grant stops
    without.counters["+1/+1"] = 1
    assert _has(eng, without, "haste")
    eng.state.battlefield.remove(exava)
    assert not _has(eng, without, "haste")  # the source left: the static stops


def test_other_merfolk_with_a_counter_checks_the_creature_type():
    eng = _engine()
    text = "Each other Merfolk you control with a +1/+1 counter on it has flying."
    namor = _put(eng, _card("Namor, Scourge of the Seas", text, "Legendary Creature — Merfolk"), counters={"+1/+1": 1})
    fish = _put(eng, _card("Fish", type_line="Creature — Merfolk"), counters={"+1/+1": 1})
    bear = _put(eng, _card("Bear"), counters={"+1/+1": 1})
    assert _has(eng, fish, "flying") and not _has(eng, bear, "flying") and not _has(eng, namor, "flying")


def test_each_permanent_with_a_counter_reaches_every_players_permanents():
    eng = _engine()
    text = "Each permanent with a divinity counter on it has indestructible."
    taken = _put(eng, _card("That Which Was Taken", text, "Legendary Artifact"))
    mine = _put(eng, _card("Mine"), counters={"divinity": 1})
    theirs = _put(eng, _card("Theirs", type_line="Land"), "p2", counters={"divinity": 1})
    plain = _put(eng, _card("Plain"), "p2")
    assert _has(eng, mine, "indestructible") and _has(eng, theirs, "indestructible")
    assert not _has(eng, plain, "indestructible") and not _has(eng, taken, "indestructible")
    theirs.counters.clear()
    assert not _has(eng, theirs, "indestructible")


def test_kindred_boon_style_you_control_does_not_reach_opponents():
    eng = _engine()
    text = "Each creature you control with a divinity counter on it has indestructible."
    boon = _put(eng, _card("Kindred Boon", text, "Enchantment"))
    mine = _put(eng, _card("Mine"), counters={"divinity": 1})
    theirs = _put(eng, _card("Theirs"), "p2", counters={"divinity": 1})
    assert _has(eng, mine, "indestructible") and not _has(eng, theirs, "indestructible")
    eng.state.battlefield.remove(boon)
    assert not _has(eng, mine, "indestructible")


# -- F2: "each creature that's a <types>" and legendary permanents ---------------------------------------------------


def test_each_creature_thats_a_type_is_global_and_other_excludes_the_source():
    eng = _engine()
    lovisa = _put(eng, _card("Lovisa Coldeyes", "Each creature that's a Barbarian, a Warrior, or a Berserker gets +2/+2 and has haste.",
                             "Legendary Creature — Human Barbarian"))
    warrior = _put(eng, _card("Warrior", type_line="Creature — Human Warrior"), "p2")
    bear = _put(eng, _card("Bear"), "p2")
    assert _pt(eng, warrior) == (4, 4) and _has(eng, warrior, "haste")  # RULE 613: global, opponents' creatures too
    assert _pt(eng, lovisa) == (4, 4)  # not "other": the source is a Barbarian itself
    assert _pt(eng, bear) == (2, 2) and not _has(eng, bear, "haste")
    eng.state.battlefield.remove(lovisa)
    assert _pt(eng, warrior) == (2, 2) and not _has(eng, warrior, "haste")

    eng = _engine()
    kaheera = _put(eng, _card("Kaheera, the Orphanguard",
                              "Each other creature you control that's a Cat, Elemental, Nightmare, Dinosaur, or Beast gets +1/+1 and has vigilance.",
                              "Legendary Creature — Cat Beast"))
    cat = _put(eng, _card("Cat", type_line="Creature — Cat"))
    their_cat = _put(eng, _card("Their cat", type_line="Creature — Cat"), "p2")
    assert _pt(eng, cat) == (3, 3) and _has(eng, cat, "vigilance")
    assert _pt(eng, kaheera) == (2, 2) and _pt(eng, their_cat) == (2, 2)  # other, and "you control"


def test_each_creature_you_control_thats_food_or_golem_uses_subtype_any():
    eng = _engine()
    text = "Each creature you control that's a Food or a Golem gets +2/+2 and has trample."
    brenard = _put(eng, _card("Brenard, Ginger Sculptor", text, "Legendary Creature — Giant Artificer"))
    golem = _put(eng, _card("Golem", type_line="Artifact Creature — Golem"))
    food = _put(eng, _card("Food", type_line="Artifact Creature — Food"))
    assert _pt(eng, golem) == (4, 4) and _pt(eng, food) == (4, 4) and _has(eng, food, "trample")
    assert _pt(eng, brenard) == (2, 2)


def test_other_legendary_permanents_you_control_have_indestructible():
    eng = _engine()
    memorial = _put(eng, _card("Avacyn's Memorial", "Other legendary permanents you control have indestructible.", "Legendary Artifact", ))
    legend = _put(eng, _card("Legend", legendary=True))
    land = _put(eng, _card("Legendary Land", type_line="Land", legendary=True))
    plain = _put(eng, _card("Plain"))
    theirs = _put(eng, _card("Their legend", legendary=True), "p2")
    assert _has(eng, legend, "indestructible") and _has(eng, land, "indestructible")
    assert not _has(eng, plain, "indestructible") and not _has(eng, theirs, "indestructible")
    assert not _has(eng, memorial, "indestructible")  # "other"
    eng.state.battlefield.remove(memorial)
    assert not _has(eng, legend, "indestructible")


# -- G1: self / host conditions --------------------------------------------------------------------------------------


def test_isnt_attacking_or_blocking_toggles_with_both_roles():
    eng = _engine()
    ace = _put(eng, _card("Intrepid Ace", "This creature gets +2/+0 as long as it isn't attacking or blocking.", "Creature — Human Pilot"))
    twin = _put(eng, _card("Twin"))
    assert _pt(eng, ace) == (4, 2) and _pt(eng, twin) == (2, 2)
    ace.attacking = True
    assert _pt(eng, ace) == (2, 2)
    ace.attacking = False
    ace.blocking = twin.instance_id
    assert _pt(eng, ace) == (2, 2)
    ace.blocking = None
    assert _pt(eng, ace) == (4, 2)


def test_life_total_at_or_above_starting_total_gates_my_creatures_only():
    eng = _engine()
    text = "As long as your life total is greater than or equal to your starting life total, creatures you control get +1/+1."
    _put(eng, _card("Path of Bravery", text, "Enchantment"))
    mine, theirs = _put(eng, _card("Mine")), _put(eng, _card("Theirs"), "p2")
    p1 = eng.state.players[0]
    assert _pt(eng, mine) == (3, 3) and _pt(eng, theirs) == (2, 2)
    p1.life = 19
    assert _pt(eng, mine) == (2, 2)
    p1.life = 25
    assert _pt(eng, mine) == (3, 3)


def test_mishras_domination_checks_who_controls_the_host():
    eng = _engine()
    text = "Enchant creature\nAs long as you control enchanted creature, it gets +2/+2. Otherwise, it can't block."
    mine, theirs = _put(eng, _card("Mine")), _put(eng, _card("Theirs"), "p2")
    aura = _aura(eng, "Mishra's Domination", text, mine)
    assert _pt(eng, mine) == (4, 4) and not _has(eng, mine, "cant_block")
    aura.attached_to = theirs.instance_id
    assert _pt(eng, theirs) == (2, 2) and _has(eng, theirs, "cant_block")  # RULE 303.4: the host, not the Aura
    assert _pt(eng, mine) == (2, 2)
    theirs.controller_id = "p1"  # layer 2: a control change flips the gate
    assert _pt(eng, theirs) == (4, 4) and not _has(eng, theirs, "cant_block")


def test_legendary_host_gates():
    eng = _engine()
    legend = _put(eng, _card("Legend", legendary=True))
    bear = _put(eng, _card("Bear"))
    research = _aura(eng, "Combat Research", "Enchant creature\nAs long as enchanted creature is legendary, it gets +1/+1 and has ward {1}.", legend)
    assert _pt(eng, legend) == (3, 3)
    research.attached_to = bear.instance_id
    assert _pt(eng, bear) == (2, 2) and _pt(eng, legend) == (2, 2)

    strike = _aura(eng, "Stunning Strike", "Enchant creature\nAs long as enchanted creature isn't legendary, it doesn't untap during its controller's untap step.", bear)
    eng.recompute_continuous_effects()
    assert continuous.has_no_untap_static(eng.state, bear) and not continuous.has_no_untap_static(eng.state, legend)
    strike.attached_to = legend.instance_id
    eng.recompute_continuous_effects()
    assert not continuous.has_no_untap_static(eng.state, legend) and not continuous.has_no_untap_static(eng.state, bear)


def test_equipment_legendary_and_either_type_gates():
    eng = _engine()
    legend = _put(eng, _card("Legend", legendary=True))
    bear = _put(eng, _card("Bear"))
    axe = _put(eng, _card("Gimli's Axe", "Equipped creature gets +2/+0.\nAs long as equipped creature is legendary, it has menace.", "Artifact — Equipment"))
    axe.attached_to = bear.instance_id
    assert not _has(eng, bear, "menace")
    axe.attached_to = legend.instance_id
    assert _has(eng, legend, "menace") and not _has(eng, bear, "menace")

    angel = _put(eng, _card("Angel", type_line="Creature — Angel"))
    human = _put(eng, _card("Human", type_line="Creature — Human"))
    bracers = _put(eng, _card("Bladed Bracers", "Equipped creature gets +1/+1.\nAs long as equipped creature is a Human or an Angel, it has vigilance.", "Artifact — Equipment"))
    for host, expected in ((angel, True), (human, True), (bear, False)):
        bracers.attached_to = host.instance_id
        assert _has(eng, host, "vigilance") is expected
    assert not _has(eng, bracers, "vigilance")  # the Equipment itself never gains what the host does


# -- self type addition ----------------------------------------------------------------------------------------------


def test_self_type_addition_follows_the_counter_threshold():
    eng = _engine()
    text = "As long as this creature has three or more +1/+1 counters on it, it has flying and is a Knight in addition to its other types."
    squire = _put(eng, _card("Skyknight Squire", text, "Creature — Human"), counters={"+1/+1": 2})
    twin = _put(eng, _card("Twin", text.replace("this creature", "this creature"), "Creature — Human"), counters={"+1/+1": 2})
    eng.recompute_continuous_effects()
    assert not squire.has_subtype("Knight") and not _has(eng, squire, "flying")
    squire.counters["+1/+1"] = 3
    eng.recompute_continuous_effects()
    assert squire.has_subtype("Knight") and squire.has_subtype("Human") and _has(eng, squire, "flying")  # in addition
    assert not twin.has_subtype("Knight")  # a same-named bystander with its own count is unaffected
    squire.counters["+1/+1"] = 1
    eng.recompute_continuous_effects()
    assert not squire.has_subtype("Knight") and not _has(eng, squire, "flying")


def test_weatherlight_compleated_becomes_a_creature_at_four_counters():
    eng = _engine()
    text = "As long as ~ has four or more phyresis counters on it, it's a Phyrexian creature in addition to its other types."
    ship = _put(eng, Card(id="w", name="Weatherlight Compleated", oracle_text=text, type_line="Legendary Artifact — Vehicle",
                          vehicle_power=4, vehicle_toughness=5))
    eng.recompute_continuous_effects()
    assert not ship.is_creature
    ship.counters["phyresis"] = 4
    eng.recompute_continuous_effects()
    assert ship.is_creature and ship.has_subtype("Phyrexian") and "artifact" in ship.type_words
    ship.counters["phyresis"] = 3
    eng.recompute_continuous_effects()
    assert not ship.is_creature and not ship.has_subtype("Phyrexian")


def test_vehicle_aura_makes_the_host_a_creature_only_while_it_is_a_vehicle():
    eng = _engine()
    text = "Enchant creature or Vehicle\nAs long as enchanted permanent is a Vehicle, it's a creature in addition to its other types.\nEnchanted creature gets +2/+2 and has flying."
    vehicle = _put(eng, Card(id="v", name="Rig", type_line="Artifact — Vehicle", vehicle_power=3, vehicle_toughness=3))
    bear = _put(eng, _card("Bear"))
    aura = _aura(eng, "Aerial Modification", text, vehicle)
    eng.recompute_continuous_effects()
    assert vehicle.is_creature
    aura.attached_to = bear.instance_id
    eng.recompute_continuous_effects()
    assert not vehicle.is_creature and not bear.has_subtype("Vehicle")


def test_awakened_awareness_sets_base_pt_only_while_a_creature():
    eng = _engine()
    text = "Enchant artifact or creature\nAs long as enchanted permanent is a creature, it has base power and toughness 1/1."
    bear = _put(eng, _card("Bear", power=4, toughness=4))
    rock = _put(eng, Card(id="r", name="Rock", type_line="Artifact", power=None, toughness=None))
    aura = _aura(eng, "Awakened Awareness", text, bear)
    assert _pt(eng, bear) == (1, 1)
    aura.attached_to = rock.instance_id
    eng.recompute_continuous_effects()
    assert not rock.is_creature and _pt(eng, bear) == (4, 4)


# -- A3: enchanted-permanent statements ------------------------------------------------------------------------------


def test_oni_possession_sets_creature_types_for_its_host_only():
    eng = _engine()
    host = _put(eng, _card("Host", type_line="Artifact Creature — Golem"), "p2")
    bystander = _put(eng, _card("Bystander", type_line="Artifact Creature — Golem"), "p2")
    aura = _aura(eng, "Oni Possession", "Enchant creature\nEnchanted creature gets +3/+3 and has trample.\nEnchanted creature is a Demon Spirit.", host)
    eng.recompute_continuous_effects()
    assert host.has_subtype("Demon") and host.has_subtype("Spirit") and not host.has_subtype("Golem")  # RULE 205.3m
    assert "artifact" in host.type_words and bystander.has_subtype("Golem")
    eng.state.battlefield.remove(aura)
    eng.recompute_continuous_effects()
    assert host.has_subtype("Golem") and not host.has_subtype("Demon")


def test_enchantmentize_replaces_card_types_but_keeps_abilities():
    eng = _engine()
    host = _put(eng, Card(id="h", name="Host", type_line="Artifact Creature — Golem", is_creature=True, power=3, toughness=3,
                          keywords=["Flying"]), "p2")
    bystander = _put(eng, Card(id="b", name="By", type_line="Artifact Creature — Golem", is_creature=True, power=3, toughness=3), "p2")
    aura = _aura(eng, "Enchantmentize", "Enchant creature or enchantment\nEnchanted permanent is an enchantment and loses all other card types. (It still has its abilities, but it's no longer a creature.)", host)
    eng.recompute_continuous_effects()
    assert not host.is_creature and "artifact" not in host.type_words and "enchantment" in host.type_words
    assert combat.has(host, "flying") and not host.loses_all_abilities  # abilities are kept
    assert bystander.is_creature and "artifact" in bystander.type_words
    eng.state.battlefield.remove(aura)
    eng.recompute_continuous_effects()
    assert host.is_creature and "artifact" in host.type_words


def test_in_bolas_clutches_makes_the_host_legendary():
    eng = _engine()
    host = _put(eng, _card("Host"), "p2")
    other = _put(eng, _card("Other"), "p2")
    aura = _aura(eng, "In Bolas's Clutches", "Enchant permanent\nYou control enchanted permanent.\nEnchanted permanent is legendary.", host)
    eng.recompute_continuous_effects()
    assert host.is_legendary and not other.is_legendary
    eng.state.battlefield.remove(aura)
    eng.recompute_continuous_effects()
    assert not host.is_legendary


def test_song_of_the_dryads_makes_a_colorless_forest_land():
    eng = _engine()
    host = _put(eng, Card(id="h", name="Host", type_line="Artifact Creature — Golem", is_creature=True, power=3, toughness=3,
                          mana_cost_string="{R}", keywords=["Flying"]), "p2")
    aura = _aura(eng, "Song of the Dryads", "Enchant permanent\nEnchanted permanent is a colorless Forest land.", host)
    eng.recompute_continuous_effects()
    assert host.is_land and not host.is_creature and "artifact" not in host.type_words  # RULE 205.1a
    assert host.has_subtype("Forest") and not host.has_subtype("Golem")
    assert host.colors == set()  # RULE 105.2c: colourless
    assert host.loses_all_abilities  # RULE 305.7: a basic land type replaces the rules text
    eng.state.battlefield.remove(aura)
    eng.recompute_continuous_effects()
    assert host.is_creature and not host.is_land and host.colors == {"R"}


@pytest.mark.parametrize("name,text,grants", [
    ("Imprisoned in the Moon", "Enchant creature, land, or planeswalker\nEnchanted permanent is a colorless land with \"{T}: Add {C}\" and loses all other card types and abilities.", "_granted_mana"),
    ("In Too Deep", "Enchant creature, planeswalker, or Clue\nEnchanted permanent is a colorless Clue artifact with \"{2}, Sacrifice this artifact: Draw a card\" and loses all other abilities.", "_granted_activated_abilities"),
    ("Sugar Coat", "Enchant creature or Food\nEnchanted permanent is a colorless Food artifact with \"{2}, {T}, Sacrifice this artifact: You gain 3 life\" and loses all other card types and abilities.", "_granted_activated_abilities"),
])
def test_colorless_type_auras_remove_the_old_abilities_and_grant_the_new_one(name, text, grants):
    eng = _engine()
    host = _put(eng, Card(id="h", name="Host", type_line="Creature — Bear", is_creature=True, power=3, toughness=3,
                          mana_cost_string="{G}", keywords=["Flying"], oracle_text="{T}: Draw a card."), "p2")
    bystander = _put(eng, Card(id="b", name="By", type_line="Creature — Bear", is_creature=True, power=3, toughness=3), "p2")
    aura = _aura(eng, name, text, host)
    eng.recompute_continuous_effects()
    assert not host.is_creature and host.colors == set()
    assert host.loses_all_abilities and not combat.has(host, "flying")  # RULE 613.7: removal first ...
    assert len(getattr(host, grants)) == 1  # ... then the ability this same Aura grants survives it
    assert bystander.is_creature and not getattr(bystander, grants)
    eng.state.battlefield.remove(aura)
    eng.recompute_continuous_effects()
    assert host.is_creature and not getattr(host, grants) and combat.has(host, "flying")


def test_essence_leak_grants_its_upkeep_trigger_only_to_a_red_or_green_host():
    eng = _engine()
    red = _put(eng, Card(id="r", name="Red", type_line="Creature — Bear", is_creature=True, power=2, toughness=2, mana_cost_string="{R}"))
    green = _put(eng, Card(id="g", name="Green", type_line="Creature — Bear", is_creature=True, power=2, toughness=2, mana_cost_string="{G}"))
    blue = _put(eng, Card(id="u", name="Blue", type_line="Creature — Bear", is_creature=True, power=2, toughness=2, mana_cost_string="{U}"))
    text = "Enchant permanent\nAs long as enchanted permanent is red or green, it has \"At the beginning of your upkeep, sacrifice this permanent unless you pay its mana cost.\""
    aura = _aura(eng, "Essence Leak", text, red)
    eng.recompute_continuous_effects()
    assert len(red._granted_triggered_abilities) == 1 and not blue._granted_triggered_abilities
    for host, count in ((green, 1), (blue, 0)):
        aura.attached_to = host.instance_id
        eng.recompute_continuous_effects()
        assert len(host._granted_triggered_abilities) == count and not red._granted_triggered_abilities


def test_de_evolve_style_creature_type_statement_in_a_compound_clause():
    eng = _engine()
    host = _put(eng, _card("Host", type_line="Creature — Golem", power=5, toughness=5), "p2")
    _aura(eng, "De-evolve", "Enchant creature\nEnchanted creature gets -4/-0, can't block, and is a Salamander. (It loses all other creature types.)", host)
    assert _pt(eng, host) == (1, 5) and _has(eng, host, "cant_block")
    assert host.has_subtype("Salamander") and not host.has_subtype("Golem")


def test_immerwolf_and_sporecrown_are_other_creatures_of_the_listed_types():
    eng = _engine()
    text = "Each other creature you control that's a Wolf or a Werewolf gets +1/+1."
    wolf_lord = _put(eng, _card("Immerwolf", text, "Creature — Wolf"))
    wolf = _put(eng, _card("Wolf", type_line="Creature — Wolf"))
    their_wolf = _put(eng, _card("Their wolf", type_line="Creature — Wolf"), "p2")
    assert _pt(eng, wolf) == (3, 3) and _pt(eng, wolf_lord) == (2, 2) and _pt(eng, their_wolf) == (2, 2)


def test_auriok_steelshaper_gate_is_its_own_equipped_state():
    eng = _engine()
    text = "As long as this creature is equipped, each creature you control that's a Soldier or a Knight gets +1/+1."
    shaper = _put(eng, _card("Auriok Steelshaper", text, "Creature — Human Soldier"))
    knight = _put(eng, _card("Knight", type_line="Creature — Human Knight"))
    their_knight = _put(eng, _card("Their knight", type_line="Creature — Human Knight"), "p2")
    assert _pt(eng, knight) == (2, 2)
    equip = _put(eng, _card("Sword", "Equipped creature gets +0/+0.", "Artifact — Equipment"))
    equip.attached_to = shaper.instance_id
    assert _pt(eng, knight) == (3, 3) and _pt(eng, shaper) == (3, 3) and _pt(eng, their_knight) == (2, 2)
    equip.attached_to = None
    assert _pt(eng, knight) == (2, 2)


def test_coalition_flag_makes_its_host_a_flagbearer_and_nothing_else():
    eng = _engine()
    host = _put(eng, _card("Host", type_line="Creature — Human Soldier"))
    other = _put(eng, _card("Other", type_line="Creature — Human Soldier"))
    aura = _aura(eng, "Coalition Flag", "Enchant creature you control\nEnchanted creature is a Flagbearer.", host)
    eng.recompute_continuous_effects()
    assert host.has_subtype("Flagbearer") and not host.has_subtype("Human") and other.has_subtype("Human")
    eng.state.battlefield.remove(aura)
    eng.recompute_continuous_effects()
    assert host.has_subtype("Human") and not host.has_subtype("Flagbearer")


def test_hero_of_bretagard_counts_counters_of_any_kind():
    eng = _engine()
    text = ("As long as this creature has five or more counters on it, it has flying and is an Angel in addition to its other types.\n"
            "As long as this creature has ten or more counters on it, it has indestructible and is a God in addition to its other types.")
    hero = _put(eng, _card("Hero of Bretagard", text, "Creature — Human Warrior"), counters={"+1/+1": 3, "time": 1})
    eng.recompute_continuous_effects()
    assert not hero.has_subtype("Angel")
    hero.counters["shield"] = 1  # RULE 122.1: 3 + 1 + 1 counters of different kinds all count
    eng.recompute_continuous_effects()
    assert hero.has_subtype("Angel") and hero.has_subtype("Human") and not hero.has_subtype("God")
    assert _has(eng, hero, "flying") and not _has(eng, hero, "indestructible")
    hero.counters["+1/+1"] = 8
    eng.recompute_continuous_effects()
    assert hero.has_subtype("God") and _has(eng, hero, "indestructible")


@pytest.mark.parametrize("name,text,granted", [
    ("Champion's Helm", "Equipped creature gets +2/+2.\nAs long as equipped creature is legendary, it has hexproof.\nEquip {1}", ["hexproof"]),
    ("Hero's Heirloom", "Equipped creature gets +2/+1.\nAs long as equipped creature is legendary, it has trample and haste.\nEquip {2}", ["trample", "haste"]),
])
def test_equipment_legendary_keyword_gate(name, text, granted):
    eng = _engine()
    legend, bear = _put(eng, _card("Legend", legendary=True)), _put(eng, _card("Bear"))
    gear = _put(eng, _card(name, text, "Artifact — Equipment"))
    gear.attached_to = bear.instance_id
    assert all(not _has(eng, bear, k) for k in granted)
    gear.attached_to = legend.instance_id
    assert all(_has(eng, legend, k) for k in granted) and all(not _has(eng, bear, k) for k in granted)

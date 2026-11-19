"""PAR-289 milestone 1: continuous statics the engine already had primitives for, now reachable from oracle text.

Each group parses the real card text, binds it on a real `GameEngine` and checks the layer effect for the condition
true, false and toggling, plus a same-type bystander outside the subject. Groups: the "Descend N" label, the
condition phrases (completed a dungeon, entered this turn, another creature entered, no opponent controls, any player
controls, card in graveyard, an opponent is poisoned), "enchanted land is a <basic type>", the "loses all abilities
and is a <type> with base power and toughness" Aura family, and the "<static>. Otherwise, <static>." pair.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_condition, static_effect_specs
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _card(name, text="", type_line="Creature — Bear", power=2, toughness=2, keywords=None):
    creature = "Creature" in type_line
    return Card(id=name, name=name, oracle_text=text, type_line=type_line, is_creature=creature,
                power=power if creature else None, toughness=toughness if creature else None,
                keywords=keywords or [])


def _engine():
    return GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0)


def _put(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _pt(eng, obj):
    eng.recompute_continuous_effects()
    return obj.power, obj.toughness


def _has(eng, obj, keyword):
    eng.recompute_continuous_effects()
    return keyword in obj.granted_keywords


def _fill_graveyard(eng, owner, n):
    player = next(p for p in eng.state.players if p.id == owner)
    for i in range(n):
        obj = GameObject(_card(f"Gy{owner}{i}", type_line="Artifact"), owner_id=owner, zone=Zone.GRAVEYARD)
        player.graveyard.append(obj)


def _enter_event(eng, name, controller):
    obj = _put(eng, _card(name), controller)
    eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, controller_id=controller, object=name,
                                   instance_id=obj.instance_id, object_types=sorted(obj.type_words)))
    return obj


# -- parser ----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name,text,type_line", [
    ("Echo of Dusk", "Descend 4 — As long as there are four or more permanent cards in your graveyard, this creature gets +1/+1 and has lifelink.", "Creature — Vampire"),
    ("Didact Echo", "Descend 4 — This creature has flying as long as there are four or more permanent cards in your graveyard.", "Creature — Illusion"),
    ("Gloom Stalker", "As long as you've completed a dungeon, this creature has double strike.", "Creature — Human"),
    ("Crew Captain", "This creature has indestructible as long as it entered this turn.", "Creature — Human"),
    ("Bristlebane Outrider", "As long as another creature entered the battlefield under your control this turn, this creature gets +2/+0.", "Creature — Kithkin"),
    ("Saddled Rimestag", "This creature gets +2/+2 as long as you had another creature enter the battlefield under your control this turn.", "Creature — Elk"),
    ("Vexing Beetle", "This creature gets +3/+3 as long as no opponent controls a creature.", "Creature — Insect"),
    ("Kavu Runner", "This creature has haste as long as no opponent controls a white or blue creature.", "Creature — Kavu"),
    ("Knight of Grace", "This creature gets +1/+0 as long as any player controls a black permanent.", "Creature — Human Knight"),
    ("Windwright Mage", "This creature has flying as long as an artifact card is in your graveyard.", "Creature — Human Wizard"),
    ("Bloodfire Enforcers", "This creature has first strike and trample as long as an instant card and a sorcery card are in your graveyard.", "Creature — Human"),
    ("Viridian Betrayers", "This creature has infect as long as an opponent is poisoned.", "Creature — Elf"),
    ("Frogify", "Enchant creature\nEnchanted creature loses all abilities and is a blue Frog creature with base power and toughness 1/1.", "Enchantment — Aura"),
    ("Lignify", "Enchant creature\nEnchanted creature is a Treefolk with base power and toughness 0/4 and loses all abilities.", "Enchantment — Aura"),
    ("Kasmina's Transmutation", "Enchant creature\nEnchanted creature loses all abilities and has base power and toughness 1/1.", "Enchantment — Aura"),
    ("Lush Growth", "Enchant land\nEnchanted land is a Mountain, Forest, and Plains.", "Enchantment — Aura"),
    ("Bonds of Faith", "Enchant creature\nEnchanted creature gets +2/+2 as long as it's a Human. Otherwise, it can't attack or block.", "Enchantment — Aura"),
    ("Evolved Spinoderm", "This creature has trample as long as it has 2 or fewer oil counters on it. Otherwise, it has hexproof.", "Creature — Beast"),
])
def test_real_card_text_is_fully_modeled(name, text, type_line):
    assert parse_oracle(_card(name, text, type_line)).modeled


@pytest.mark.parametrize("phrase", [
    "no opponent controls", "any player controls", "it's modified", "you're the", "it entered last turn",
])
def test_unknown_condition_phrases_fail_closed(phrase):
    assert static_condition(phrase) is None


def test_host_pronoun_condition_never_reads_the_aura():
    """RULE 303.4: "it" is the host; a pronoun phrase the grammar cannot read for the host fails closed."""
    specs = static_effect_specs("enchanted creature gets +2/+2 as long as it's a human.")
    assert specs[0].params["active_if"] == {"kind": "is_subtype", "subtype": "human", "of": "attached"}
    assert static_effect_specs("enchanted creature gets +2/+2 as long as it entered this turn.") is None
    assert static_effect_specs("enchanted creature gets +2/+2 as long as it has 3 or more +1/+1 counters on it.") is None


def test_otherwise_pair_needs_both_halves():
    assert static_effect_specs("enchanted creature gets +2/+2 as long as it's a human. otherwise, it flies high.") is None
    assert static_effect_specs("enchanted creature gets +2/+2. otherwise, it gets -2/-2.") is None


# -- descend ---------------------------------------------------------------------------------------------------------


def test_descend_label_gates_on_your_graveyard_only():
    eng = _engine()
    echo = _put(eng, _card("Echo of Dusk", "Descend 4 — As long as there are four or more permanent cards in your graveyard, this creature gets +1/+1 and has lifelink.", "Creature — Vampire"))
    bystander = _put(eng, _card("Bystander"))
    _fill_graveyard(eng, "p1", 3)
    assert _pt(eng, echo) == (2, 2) and not _has(eng, echo, "lifelink")
    _fill_graveyard(eng, "p2", 4)  # RULE 700.11: only *your* graveyard counts
    assert _pt(eng, echo) == (2, 2)
    _fill_graveyard(eng, "p1", 1)
    assert _pt(eng, echo) == (3, 3) and _has(eng, echo, "lifelink")
    assert _pt(eng, bystander) == (2, 2) and not _has(eng, bystander, "lifelink")
    next(p for p in eng.state.players if p.id == "p1").graveyard.pop()
    assert _pt(eng, echo) == (2, 2) and not _has(eng, echo, "lifelink")


# -- condition phrases -----------------------------------------------------------------------------------------------


def test_completed_a_dungeon_is_a_player_designation():
    eng = _engine()
    stalker = _put(eng, _card("Gloom Stalker", "As long as you've completed a dungeon, this creature has double strike.", "Creature — Human"))
    theirs = _put(eng, _card("Gloom Stalker", "As long as you've completed a dungeon, this creature has double strike.", "Creature — Human"), "p2")
    p1, p2 = eng.state.players
    assert not _has(eng, stalker, "double_strike")
    p2.completed_dungeons.append("Tomb of Annihilation")
    assert not _has(eng, stalker, "double_strike") and _has(eng, theirs, "double_strike")
    p1.completed_dungeons.append("Lost Mine of Phandelver")
    assert _has(eng, stalker, "double_strike")
    p1.completed_dungeons.clear()
    assert not _has(eng, stalker, "double_strike")


def test_entered_this_turn_stops_after_the_turn_changes():
    eng = _engine()
    captain = _put(eng, _card("Crew Captain", "This creature has indestructible as long as it entered this turn.", "Creature — Human"))
    other = _put(eng, _card("Other"))
    assert _has(eng, captain, "indestructible") and not _has(eng, other, "indestructible")
    captain.turn_entered = eng.state.internal_turn.number - 1
    assert not _has(eng, captain, "indestructible")


def test_another_creature_entered_ignores_self_and_opponents():
    eng = _engine()
    text = "As long as another creature entered the battlefield under your control this turn, this creature gets +2/+0."
    outrider = _put(eng, _card("Bristlebane Outrider", text, "Creature — Kithkin"))
    eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, controller_id="p1", object="Bristlebane Outrider",
                                   instance_id=outrider.instance_id, object_types=["creature"]))
    assert _pt(eng, outrider) == (2, 2)  # RULE 603.2: "another" never counts the source itself
    _enter_event(eng, "Their Bear", "p2")
    assert _pt(eng, outrider) == (2, 2)
    _enter_event(eng, "My Bear", "p1")
    assert _pt(eng, outrider) == (4, 2)


def test_no_opponent_controls_a_creature_toggles():
    eng = _engine()
    beetle = _put(eng, _card("Vexing Beetle", "This creature gets +3/+3 as long as no opponent controls a creature.", "Creature — Insect", 3, 3))
    twin = _put(eng, _card("Plain"))
    assert _pt(eng, beetle) == (6, 6) and _pt(eng, twin) == (2, 2)
    foe = _put(eng, _card("Foe"), "p2")
    assert _pt(eng, beetle) == (3, 3)
    eng.state.battlefield.remove(foe)
    assert _pt(eng, beetle) == (6, 6)


def test_any_player_controls_a_black_permanent_counts_both_sides_but_not_colorless():
    eng = _engine()
    text = "This creature gets +1/+0 as long as any player controls a black permanent."
    knight = _put(eng, _card("Knight of Grace", text, "Creature — Human Knight"))
    assert _pt(eng, knight) == (2, 2)
    _put(eng, Card(id="c", name="Colorless", type_line="Artifact"), "p2")
    assert _pt(eng, knight) == (2, 2)
    black = Card(id="b", name="Black Thing", type_line="Creature — Zombie", is_creature=True, power=1, toughness=1, mana_cost_string="{B}")
    theirs = _put(eng, black, "p2")
    assert _pt(eng, knight) == (3, 2)
    eng.state.battlefield.remove(theirs)
    assert _pt(eng, knight) == (2, 2)
    _put(eng, black, "p1")
    assert _pt(eng, knight) == (3, 2)


def test_card_in_your_graveyard_and_conjunction():
    eng = _engine()
    mage = _put(eng, _card("Windwright Mage", "This creature has flying as long as an artifact card is in your graveyard.", "Creature — Human Wizard"))
    both = _put(eng, _card("Bloodfire Enforcers", "This creature has first strike and trample as long as an instant card and a sorcery card are in your graveyard.", "Creature — Human"))
    p1 = eng.state.players[0]

    def bury(types, owner="p1"):
        obj = GameObject(_card("Bury", type_line=types), owner_id=owner, zone=Zone.GRAVEYARD)
        next(p for p in eng.state.players if p.id == owner).graveyard.append(obj)

    bury("Artifact", "p2")
    assert not _has(eng, mage, "flying")  # an opponent's graveyard is not yours
    bury("Instant")
    assert not _has(eng, both, "first_strike")  # RULE 700.5-style conjunction: both halves must hold
    bury("Sorcery")
    assert _has(eng, both, "first_strike") and _has(eng, both, "trample") and not _has(eng, mage, "flying")
    bury("Artifact")
    assert _has(eng, mage, "flying")
    p1.graveyard.clear()
    assert not _has(eng, mage, "flying") and not _has(eng, both, "trample")


def test_an_opponent_is_poisoned_reads_opponents_only():
    eng = _engine()
    text = "This creature has infect as long as an opponent is poisoned."
    mine = _put(eng, _card("Viridian Betrayers", text, "Creature — Elf"))
    p1, p2 = eng.state.players
    p1.poison = 3
    assert not _has(eng, mine, "infect")
    p2.poison = 1
    assert _has(eng, mine, "infect")
    p2.poison = 0
    assert not _has(eng, mine, "infect")


# -- Aura transformations --------------------------------------------------------------------------------------------


def _aura(eng, name, text, host, controller="p1"):
    aura = _put(eng, _card(name, text, "Enchantment — Aura"), controller)
    aura.attached_to = host.instance_id
    return aura


def test_frogify_transforms_only_its_host_and_ends_with_the_aura():
    eng = _engine()
    host = _put(eng, Card(id="h", name="Host", type_line="Artifact Creature — Golem", is_creature=True, power=5, toughness=5,
                          keywords=["Flying"], mana_cost_string="{R}"), "p2")
    bystander = _put(eng, _card("Bystander", type_line="Artifact Creature — Golem", power=4, toughness=4, keywords=["Trample"]), "p2")
    aura = _aura(eng, "Frogify", "Enchant creature\nEnchanted creature loses all abilities and is a blue Frog creature with base power and toughness 1/1.", host)
    eng.recompute_continuous_effects()
    assert (host.power, host.toughness) == (1, 1)
    assert host.has_subtype("Frog") and not host.has_subtype("Golem")  # RULE 205.3m: creature types replaced
    assert host.colors == {"U"}
    assert "artifact" not in host.type_words and host.is_creature  # RULE 205.1a: the stated card type replaces
    assert host.loses_all_abilities and "flying" not in host.granted_keywords
    assert (bystander.power, bystander.toughness) == (4, 4) and bystander.has_subtype("Golem")
    assert not bystander.loses_all_abilities
    aura.attached_to = bystander.instance_id  # RULE 303.4: the effect follows the Aura's host
    eng.recompute_continuous_effects()
    assert (host.power, host.toughness) == (5, 5) and host.has_subtype("Golem") and not host.loses_all_abilities
    assert (bystander.power, bystander.toughness) == (1, 1) and bystander.has_subtype("Frog")
    eng.state.battlefield.remove(aura)
    eng.recompute_continuous_effects()
    assert (bystander.power, bystander.toughness) == (4, 4) and bystander.has_subtype("Golem")


def test_lignify_keeps_card_types_and_other_colors():
    eng = _engine()
    host = _put(eng, Card(id="h", name="Host", type_line="Artifact Creature — Golem", is_creature=True, power=5, toughness=5, mana_cost_string="{R}"))
    _aura(eng, "Lignify", "Enchant creature\nEnchanted creature is a Treefolk with base power and toughness 0/4 and loses all abilities.", host)
    eng.recompute_continuous_effects()
    assert (host.power, host.toughness) == (0, 4) and host.has_subtype("Treefolk") and not host.has_subtype("Golem")
    assert "artifact" in host.type_words and host.colors == {"R"}


def test_kasmina_base_pt_is_a_layer_7b_set_that_counters_and_pumps_still_modify():
    eng = _engine()
    host = _put(eng, _card("Host", power=5, toughness=5, keywords=["Flying"]))
    _aura(eng, "Kasmina's Transmutation", "Enchant creature\nEnchanted creature loses all abilities and has base power and toughness 1/1.", host)
    _put(eng, _card("Anthem", "Creatures you control get +1/+1.", "Enchantment"))
    assert _pt(eng, host) == (2, 2)  # RULE 613.4: base set first (7b), the anthem applies afterwards (7c)
    assert "flying" not in host.granted_keywords and host.loses_all_abilities


def test_enchanted_land_is_a_swamp_replaces_land_types_and_abilities():
    eng = _engine()
    forest = _put(eng, Card(id="f", name="Forest", type_line="Basic Land — Forest", is_land=True))
    other = _put(eng, Card(id="f2", name="Forest", type_line="Basic Land — Forest", is_land=True))
    aura = _aura(eng, "Evil Presence", "Enchant land\nEnchanted land is a Swamp.", forest)
    eng.recompute_continuous_effects()
    assert forest.has_subtype("Swamp") and not forest.has_subtype("Forest")  # RULE 305.7
    assert other.has_subtype("Forest") and not other.has_subtype("Swamp")
    eng.state.battlefield.remove(aura)
    eng.recompute_continuous_effects()
    assert forest.has_subtype("Forest") and not forest.has_subtype("Swamp")


def test_lush_growth_gives_all_three_types():
    eng = _engine()
    land = _put(eng, Card(id="s", name="Swamp", type_line="Basic Land — Swamp", is_land=True))
    _aura(eng, "Lush Growth", "Enchant land\nEnchanted land is a Mountain, Forest, and Plains.", land)
    eng.recompute_continuous_effects()
    assert all(land.has_subtype(t) for t in ("Mountain", "Forest", "Plains")) and not land.has_subtype("Swamp")


# -- Otherwise pair --------------------------------------------------------------------------------------------------

BONDS = "Enchant creature\nEnchanted creature gets +2/+2 as long as it's a Human. Otherwise, it can't attack or block."


def test_bonds_of_faith_reads_the_host_not_the_aura_and_toggles():
    eng = _engine()
    human = _put(eng, _card("Human", type_line="Creature — Human"))
    bear = _put(eng, _card("Bear"))
    aura = _aura(eng, "Bonds of Faith", BONDS, human)
    assert _pt(eng, human) == (4, 4) and not _has(eng, human, "cant_attack")
    assert _pt(eng, bear) == (2, 2)
    aura.attached_to = bear.instance_id
    assert _pt(eng, bear) == (2, 2) and _has(eng, bear, "cant_attack") and _has(eng, bear, "cant_block")
    assert _pt(eng, human) == (2, 2) and not _has(eng, human, "cant_attack")
    # RULE 613.1d: a second Aura making the host a Human flips the gate back without touching the Bonds source.
    _aura(eng, "Frogify", "Enchant creature\nEnchanted creature is a Human with base power and toughness 1/1 and loses all abilities.", bear, "p2")
    eng.recompute_continuous_effects()
    assert bear.has_subtype("Human") and (bear.power, bear.toughness) == (3, 3) and not _has(eng, bear, "cant_attack")


def test_serra_boon_colour_pair():
    eng = _engine()
    text = "Enchant creature\nEnchanted creature gets +1/+2 as long as it's white. Otherwise, it gets -2/-1."
    white = _put(eng, Card(id="w", name="White", type_line="Creature — Bear", is_creature=True, power=2, toughness=2, mana_cost_string="{W}"))
    red = _put(eng, Card(id="r", name="Red", type_line="Creature — Bear", is_creature=True, power=2, toughness=2, mana_cost_string="{R}"))
    aura = _aura(eng, "Serra's Boon", text, white)
    assert _pt(eng, white) == (3, 4)
    aura.attached_to = red.instance_id
    assert _pt(eng, red) == (0, 1) and _pt(eng, white) == (2, 2)


def test_spinoderm_counter_toggle_on_the_source():
    eng = _engine()
    text = "This creature has trample as long as it has 2 or fewer oil counters on it. Otherwise, it has hexproof."
    spin = _put(eng, _card("Evolved Spinoderm", text, "Creature — Beast"))
    twin = _put(eng, _card("Twin", text.replace("Evolved Spinoderm", "Twin"), "Creature — Beast"))
    assert _has(eng, spin, "trample") and not _has(eng, spin, "hexproof")
    spin.counters["oil"] = 3
    assert not _has(eng, spin, "trample") and _has(eng, spin, "hexproof")
    assert _has(eng, twin, "trample") and not _has(eng, twin, "hexproof")  # the counters are per source


def test_tahngarth_rage_swaps_at_combat():
    eng = _engine()
    text = "Enchant creature\nEnchanted creature gets +3/+0 as long as it's attacking. Otherwise, it gets -2/-1."
    host = _put(eng, _card("Host", power=4, toughness=4))
    _aura(eng, "Tahngarth's Rage", text, host)
    assert _pt(eng, host) == (2, 3)
    host.attacking = True
    assert _pt(eng, host) == (7, 4)
    host.attacking = False
    assert _pt(eng, host) == (2, 3)


def test_replacement_half_keeps_the_pair_unclaimed():
    """Armament of Nyx: a prevention effect cannot ride in the same static ability, so the card stays open."""
    text = ("enchanted creature has double strike as long as it's an enchantment. "
            "otherwise, prevent all damage that would be dealt by enchanted creature.")
    assert static_effect_specs(text) is None


# -- real cards from the cache ---------------------------------------------------------------------------------------


def _real(name):
    from mtg_analyzer.services.card_database import DEFAULT_DB_PATH, CardDatabase

    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    return card


@pytest.mark.parametrize("name", [
    "Echo of Dusk", "Didact Echo", "Gloom Stalker", "Cloister Gargoyle", "Crew Captain", "Drownyard Behemoth",
    "Bristlebane Outrider", "Saddled Rimestag", "Vexing Beetle", "Kavu Runner", "Skittish Kavu", "Knight of Grace",
    "Knight of Malice", "Windwright Mage", "Vengeful Firebrand", "Viridian Betrayers", "Frogify", "Amphibian Downpour",
    "Fowl Play", "Lignify", "Kasmina's Transmutation", "Contaminated Ground", "Evil Presence", "Lingering Mirage",
    "Lush Growth", "Bonds of Faith", "Gift of Fangs", "Nyx Infusion", "Serra's Boon", "Phyrexian Boon", "Sea Legs",
    "Tahngarth's Rage", "Clutch of Undeath", "Evolved Spinoderm",
])
def test_real_cards_are_modeled(name):
    assert parse_oracle(_real(name)).modeled


def test_real_cards_execute_on_the_board():
    """Eight real cards bound from their cached oracle text and read through the layer engine."""
    eng = _engine()
    p1, p2 = eng.state.players
    # Self-gated creatures.
    beetle = _put(eng, _real("Vexing Beetle"))
    captain = _put(eng, _real("Crew Captain"))
    gargoyle = _put(eng, _real("Cloister Gargoyle"))
    eng.recompute_continuous_effects()
    echo = _put(eng, _real("Echo of Dusk"))  # printed black (like Betrayers), so placed after the Knight's baseline
    betrayers = _put(eng, _real("Viridian Betrayers"))
    base = {o: (o.power, o.toughness) for o in (beetle, gargoyle)}
    base[echo] = (echo.power, echo.toughness)
    assert beetle.power == 3 + 3 and "indestructible" in captain.granted_keywords  # no opposing creature, entered now
    assert "infect" not in betrayers.granted_keywords and "flying" not in gargoyle.granted_keywords
    p2.poison = 1
    p1.completed_dungeons.append("Dungeon of the Mad Mage")
    _fill_graveyard(eng, "p1", 4)
    foe = _put(eng, Card(id="b", name="Foe", type_line="Creature — Zombie", is_creature=True, power=1, toughness=1,
                         mana_cost_string="{B}"), "p2")
    eng.recompute_continuous_effects()
    assert "infect" in betrayers.granted_keywords and "flying" in gargoyle.granted_keywords
    assert beetle.power == base[beetle][0] - 3
    assert echo.power == base[echo][0] + 1 and "lifelink" in echo.granted_keywords
    # Auras on the opponent's creature.
    for aura_name, check in [
        ("Frogify", lambda: (foe.power, foe.toughness) == (1, 1) and foe.has_subtype("Frog") and foe.colors == {"U"}),
        ("Fowl Play", lambda: foe.has_subtype("Bird") and foe.loses_all_abilities),
        ("Kasmina's Transmutation", lambda: (foe.power, foe.toughness) == (1, 1)),
        ("Lignify", lambda: (foe.power, foe.toughness) == (0, 4) and foe.has_subtype("Treefolk")),
    ]:
        aura = _aura(eng, aura_name, _real(aura_name).oracle_text, foe)
        eng.recompute_continuous_effects()
        assert check(), aura_name
        eng.state.battlefield.remove(aura)
    land = _put(eng, Card(id="f", name="Forest", type_line="Basic Land — Forest", is_land=True))
    for aura_name, types in [("Contaminated Ground", {"Swamp"}), ("Lush Growth", {"Mountain", "Forest", "Plains"})]:
        aura = _aura(eng, aura_name, _real(aura_name).oracle_text, land)
        eng.recompute_continuous_effects()
        assert all(land.has_subtype(t) for t in types), aura_name
        eng.state.battlefield.remove(aura)


def test_akawalli_stacks_its_two_descend_tiers_independently():
    """"Descend 8 — ... gets an additional +2/+2": each tier keeps its own threshold behind the stripped label."""
    eng = _engine()
    akawalli = _put(eng, _real("Akawalli, the Seething Tower"))
    base = (akawalli.power, akawalli.toughness)
    _fill_graveyard(eng, "p1", 4)
    assert _pt(eng, akawalli) == (base[0] + 2, base[1] + 2) and _has(eng, akawalli, "trample")
    _fill_graveyard(eng, "p1", 4)
    assert _pt(eng, akawalli) == (base[0] + 4, base[1] + 4)
    next(p for p in eng.state.players if p.id == "p1").graveyard[:] = []
    assert _pt(eng, akawalli) == base and not _has(eng, akawalli, "trample")


def test_flying_drone_activation_discount_needs_another_flier_that_entered_under_your_control():
    eng = _engine()
    drone = _put(eng, _real("Flying Drone"))
    ability = next(a for a in drone.activated_abilities if a.cost is not None and getattr(a.cost, "dynamic_reduction", None))
    full = eng._reduced_activation_mana(drone, ability.cost.mana, ability.cost, activating_player_id="p1")

    def enter(name, controller, keywords):
        obj = _put(eng, _card(name, keywords=keywords), controller)
        eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, controller_id=controller, object=name,
                                       instance_id=obj.instance_id, object_types=["creature"]))

    enter("Their Flier", "p2", ["Flying"])
    enter("My Walker", "p1", [])
    assert eng._reduced_activation_mana(drone, ability.cost.mana, ability.cost, activating_player_id="p1").converted_mana_cost == full.converted_mana_cost
    enter("My Flier", "p1", ["Flying"])
    assert eng._reduced_activation_mana(drone, ability.cost.mana, ability.cost, activating_player_id="p1").converted_mana_cost == full.converted_mana_cost - 2

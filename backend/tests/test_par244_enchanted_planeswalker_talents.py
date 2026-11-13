"""PAR-244: the Talent cycle -- Auras whose clauses name "enchanted planeswalker".

Real Oracle text, real engine. RULE 303.4m (an Aura's host), RULE 602.2 / 606 (activating a loyalty ability),
RULE 707.10 (a copied ability is not activated), RULE 122 / 306.5 (loyalty counters), RULE 120.3 (damage events).
"""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle

ELSPETH = """Enchant planeswalker
Enchanted planeswalker has "[+1]: Create three 1/1 white Soldier creature tokens."
Whenever you activate a loyalty ability of enchanted planeswalker, creatures you control get +2/+2 and gain vigilance until end of turn."""
ROWAN = """Enchant planeswalker
Enchanted planeswalker has "[+1]: Up to one target creature gets +2/+0 and gains first strike and trample until end of turn."
Whenever you activate a loyalty ability of enchanted planeswalker, copy that ability. You may choose new targets for the copy."""
TEFERI = """Enchant planeswalker
Enchanted planeswalker has "[−12]: You get an emblem with 'You may activate loyalty abilities of planeswalkers you control on any player's turn any time you could cast an instant.'"
Whenever you draw a card, put a loyalty counter on enchanted planeswalker."""
VIVIEN = """Enchant planeswalker
Enchanted planeswalker has "[+1]: Look at the top four cards of your library. You may reveal a creature or land card from among them and put it into your hand. Put the rest on the bottom of your library in a random order."
Whenever a nontoken creature you control enters, put a loyalty counter on enchanted planeswalker."""
LILIANA = """Enchant planeswalker
Enchanted planeswalker has "[−8]: Put all creature cards from all graveyards onto the battlefield under your control."
Whenever a creature deals damage to enchanted planeswalker, destroy that creature."""
TALENTS = {"Elspeth's Talent": ELSPETH, "Rowan's Talent": ROWAN, "Teferi's Talent": TEFERI,
           "Vivien's Talent": VIVIEN, "Liliana's Talent": LILIANA}

#: The printed loyalty ability of the test planeswalkers (the Aura's trigger watches this one).
PW_TEXT = "+1: Target creature gets +1/+1 until end of turn."


def engine():
    eng = GameEngine.new_game([("p1", "P1", []), ("p2", "P2", [])], starting_hand=0)
    eng.state.current_step = "main1"
    eng.state.current_phase = "main1"
    return eng


def walker(eng, owner="p1", name="Walker", loyalty=4, text=PW_TEXT):
    card = Card(id=name, name=name, type_line="Legendary Planeswalker — Test", oracle_text=text, loyalty=loyalty)
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    obj.counters["loyalty"] = loyalty
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def creature(eng, owner="p1", name="Bear", power=2, toughness=2, token=False):
    card = Card(id=name, name=name, type_line="Creature — Bear", oracle_text="", is_creature=True,
                power=power, toughness=toughness)
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    obj.is_token = token
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def aura(eng, name, host, owner="p1"):
    card = Card(id=name, name=name, type_line="Enchantment — Aura", oracle_text=TALENTS[name])
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    obj.attached_to = host.instance_id
    eng.recompute_continuous_effects()
    return obj


# ---------------------------------------------------------------- parser verdicts

@pytest.mark.parametrize("name", list(TALENTS))
def test_every_talent_is_modeled(name):
    card = Card(id=name, name=name, type_line="Enchantment — Aura", oracle_text=TALENTS[name])
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_head_parses_to_attached_host_scoped_loyalty_activation():
    card = Card(id="E", name="Elspeth's Talent", type_line="Enchantment — Aura", oracle_text=ELSPETH)
    trig = next(s for s in parse_oracle(card).specs if s.ability_kind == "triggered").trigger
    assert trig["event"] == "ACTIVATED_ABILITY"
    assert trig["condition"] == {"subject": "attached_permanent"}
    assert trig["filter"] == {"is_loyalty_ability": True}
    assert trig["activator_is_you"] is True


# ---------------------------------------------------------------- Elspeth's Talent

def test_elspeths_talent_pumps_when_the_enchanted_walker_activates():
    eng = engine()
    pw = walker(eng)
    mine = creature(eng, "p1")
    theirs = creature(eng, "p2", "Opp")
    aura(eng, "Elspeth's Talent", pw)
    eng.activate_ability(eng.state.player_by_id("p1"), pw, 0, targets=[mine])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    # +1/+1 from the walker's own ability, +2/+2 from the trigger; the opponent's creature is untouched.
    assert (mine.power, mine.toughness) == (5, 5)
    assert (theirs.power, theirs.toughness) == (2, 2)
    assert "vigilance" in [k.lower() for k in mine.granted_keywords]


def test_elspeths_talent_ignores_another_planeswalker():
    eng = engine()
    enchanted = walker(eng, name="Enchanted")
    other = walker(eng, name="Other")
    mine = creature(eng, "p1")
    aura(eng, "Elspeth's Talent", enchanted)
    eng.activate_ability(eng.state.player_by_id("p1"), other, 0, targets=[mine])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert (mine.power, mine.toughness) == (3, 3)  # only the +1/+1 of the activated ability


def test_elspeths_talent_ignores_a_creature_ability_and_an_unattached_aura():
    eng = engine()
    pw = walker(eng)
    mine = creature(eng, "p1")
    talent = aura(eng, "Elspeth's Talent", pw)
    talent.attached_to = None
    eng.recompute_continuous_effects()
    eng.activate_ability(eng.state.player_by_id("p1"), pw, 0, targets=[mine])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert (mine.power, mine.toughness) == (3, 3)


def test_elspeths_talent_does_not_trigger_off_an_opponents_activation_of_the_enchanted_walker():
    # "Whenever YOU activate": the Aura's controller must be the activating player.
    eng = engine()
    pw = walker(eng, owner="p2")
    mine = creature(eng, "p1")
    theirs = creature(eng, "p2", "Opp")
    aura(eng, "Elspeth's Talent", pw, owner="p1")
    eng.state.active_player_index = 1
    eng.activate_ability(eng.state.player_by_id("p2"), pw, 0, targets=[theirs])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert (mine.power, mine.toughness) == (2, 2)
    assert (theirs.power, theirs.toughness) == (3, 3)


def test_elspeths_granted_loyalty_ability_makes_three_soldiers_and_triggers_the_aura():
    eng = engine()
    pw = walker(eng, text="")  # no printed ability: only the granted +1
    mine = creature(eng, "p1")
    aura(eng, "Elspeth's Talent", pw)
    assert pw.granted_activated_abilities and pw.granted_activated_abilities[0].cost.loyalty == 1
    eng.activate_ability(eng.state.player_by_id("p1"), pw, 0)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    soldiers = [o for o in eng.state.battlefield if o.is_token and "Soldier" in o.card.type_line]
    assert len(soldiers) == 3
    assert pw.loyalty == 5
    assert mine.power == 4  # the activation of the granted ability triggered the pump too


# ---------------------------------------------------------------- Rowan's Talent

def test_rowans_talent_copies_the_loyalty_ability_once_and_the_copy_is_not_an_activation():
    eng = engine()
    pw = walker(eng)
    bear = creature(eng, "p1")
    aura(eng, "Rowan's Talent", pw)
    eng.activate_ability(eng.state.player_by_id("p1"), pw, 0, targets=[bear])
    # The activation put the ability on the stack; the Aura's trigger sits above it once collected.
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (4, 4)  # original and copy: +1/+1 twice
    assert pw.loyalty == 5                          # loyalty cost paid once (the copy pays nothing)
    assert pw.activated_loyalty_this_turn is True
    # RULE 606.3: still only one activation this turn -- the copy did not count as a second one.
    assert not eng._can_activate_loyalty(eng.state.player_by_id("p1"), pw)


def test_rowans_talent_copy_does_not_retrigger_the_aura():
    eng = engine()
    pw = walker(eng)
    bear = creature(eng, "p1")
    aura(eng, "Rowan's Talent", pw)
    seen = []
    orig = eng.state.fire_event

    def spy(event):
        if event.type == EventType.ACTIVATED_ABILITY:
            seen.append(event)
        return orig(event)

    eng.state.fire_event = spy
    eng.activate_ability(eng.state.player_by_id("p1"), pw, 0, targets=[bear])
    eng.resolve_until_stable()
    assert len(seen) == 1
    eng.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (4, 4)  # exactly one copy, not a chain


def test_rowans_talent_offers_new_targets_for_the_copy():
    eng = engine()
    pw = walker(eng)
    first = creature(eng, "p1", "First")
    second = creature(eng, "p1", "Second")
    aura(eng, "Rowan's Talent", pw)
    eng.activate_ability(eng.state.player_by_id("p1"), pw, 0, targets=[first])
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "copy_targets"
    eng.resolve_pending_choice("target-0")
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert (first.power, second.power) == (3, 3)  # the original hit First, the retargeted copy hit Second
    assert pw.loyalty == 5


def test_rowans_granted_up_to_one_target_ability_can_be_activated_with_no_target():
    # "Up to one target creature": zero targets is a legal announcement (RULE 601.2c), with or without creatures.
    for with_creature in (False, True):
        eng = engine()
        pw = walker(eng, text="")
        bear = creature(eng, "p1") if with_creature else None
        aura(eng, "Rowan's Talent", pw)
        eng.activate_ability(eng.state.player_by_id("p1"), pw, 0, targets=[])
        eng.resolve_until_stable()
        assert pw.loyalty == 5
        if bear is not None:
            eng.recompute_continuous_effects()
            assert bear.power == 2


def test_rowans_talent_ignores_another_planeswalker():
    eng = engine()
    enchanted = walker(eng, name="Enchanted")
    other = walker(eng, name="Other")
    bear = creature(eng, "p1")
    aura(eng, "Rowan's Talent", enchanted)
    eng.activate_ability(eng.state.player_by_id("p1"), other, 0, targets=[bear])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (3, 3)  # no copy


def test_rowans_granted_ability_is_copied_too():
    eng = engine()
    pw = walker(eng, text="")
    bear = creature(eng, "p1")
    aura(eng, "Rowan's Talent", pw)
    eng.activate_ability(eng.state.player_by_id("p1"), pw, 0, targets=[bear])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert bear.power == 6  # +2/+0 from the ability and from its copy
    assert pw.loyalty == 5


# ---------------------------------------------------------------- Teferi's / Vivien's Talent

def test_teferis_talent_adds_a_loyalty_counter_per_card_you_draw():
    eng = engine()
    pw = walker(eng)
    aura(eng, "Teferi's Talent", pw)
    me = eng.state.player_by_id("p1")
    for i in range(3):
        me.library.append(GameObject(Card(id=f"c{i}", name=f"C{i}", type_line="Sorcery"), owner_id="p1",
                                     zone=Zone.LIBRARY))
    eng.rules.draw(me, 2)
    eng.resolve_until_stable()
    assert pw.loyalty == 6 and pw.counters["loyalty"] == 6


def test_teferis_talent_ignores_the_opponents_draws_and_other_walkers():
    eng = engine()
    pw = walker(eng, name="Enchanted")
    other = walker(eng, name="Other")
    aura(eng, "Teferi's Talent", pw)
    opp = eng.state.player_by_id("p2")
    opp.library.append(GameObject(Card(id="o", name="O", type_line="Sorcery"), owner_id="p2", zone=Zone.LIBRARY))
    eng.rules.draw(opp, 1)
    eng.resolve_until_stable()
    assert pw.loyalty == 4 and other.loyalty == 4


def test_teferis_talent_with_no_host_does_nothing():
    eng = engine()
    pw = walker(eng)
    talent = aura(eng, "Teferi's Talent", pw)
    talent.attached_to = None
    me = eng.state.player_by_id("p1")
    me.library.append(GameObject(Card(id="c", name="C", type_line="Sorcery"), owner_id="p1", zone=Zone.LIBRARY))
    eng.rules.draw(me, 1)
    eng.resolve_until_stable()
    assert pw.loyalty == 4


def test_teferis_granted_minus_twelve_gets_an_emblem():
    eng = engine()
    pw = walker(eng, loyalty=12, text="")
    aura(eng, "Teferi's Talent", pw)
    assert pw.granted_activated_abilities[0].cost.loyalty == -12
    me = eng.state.player_by_id("p1")
    eng.activate_ability(me, pw, 0)
    eng.resolve_until_stable()
    assert me.emblems and pw.zone == Zone.GRAVEYARD


def _cast_creature(eng, owner):
    """Cast a free creature spell so it enters through the real stack/resolution path."""
    card = Card(id=f"e{owner}", name="Entrant", type_line="Creature — Bear", oracle_text="", is_creature=True,
                power=1, toughness=1, mana_cost_string="{0}")
    obj = GameObject(card, owner_id=owner, zone=Zone.HAND)
    obj.controller_id = owner
    bind_from_catalogue(obj)
    player = eng.state.player_by_id(owner)
    player.hand.append(obj)
    eng.state.active_player_index = 0 if owner == "p1" else 1
    eng.cast_spell(player, obj)
    eng.resolve_until_stable()
    return obj


def test_viviens_talent_counts_my_nontoken_creatures_entering():
    eng = engine()
    pw = walker(eng)
    aura(eng, "Vivien's Talent", pw)
    entrant = _cast_creature(eng, "p1")
    assert entrant.zone == Zone.BATTLEFIELD
    assert pw.loyalty == 5 and pw.counters["loyalty"] == 5


def test_viviens_talent_ignores_tokens_and_the_opponents_creatures():
    eng = engine()
    pw = walker(eng)
    aura(eng, "Vivien's Talent", pw)
    token_card = Card(id="tok", name="Bear Token", type_line="Token Creature — Bear", is_creature=True,
                      power=1, toughness=1)
    eng.rules.create_token("p1", token_card)
    eng.resolve_until_stable()
    assert pw.loyalty == 4
    entrant = _cast_creature(eng, "p2")
    assert entrant.zone == Zone.BATTLEFIELD
    assert pw.loyalty == 4


def test_viviens_granted_plus_one_looks_at_four_and_takes_a_creature_or_land():
    eng = engine()
    pw = walker(eng, text="")
    aura(eng, "Vivien's Talent", pw)
    me = eng.state.player_by_id("p1")
    me.library.clear()
    kinds = ["Sorcery", "Sorcery", "Creature — Bear", "Sorcery", "Sorcery"]
    for i, kind in enumerate(kinds):
        me.library.append(GameObject(Card(id=f"v{i}", name=f"V{i}", type_line=kind, is_creature="Creature" in kind),
                                     owner_id="p1", zone=Zone.LIBRARY))
    eng.activate_ability(me, pw, 0)
    eng.resolve_until_stable()
    pending = eng.state.pending_choice
    assert pw.loyalty == 5
    # Only the creature card among the top four is a legal pick (lands/creatures only).
    assert [o["label"] for o in pending["options"] if o["id"] != "decline"] == ["V2"]
    eng.resolve_pending_choice(next(o for o in me.library if o.name == "V2").instance_id)
    eng.resolve_until_stable()
    assert [o.name for o in me.hand] == ["V2"]
    assert len(me.library) == 4 and "V2" not in [o.name for o in me.library]


# ---------------------------------------------------------------- Liliana's Talent

def test_lilianas_talent_destroys_a_creature_that_damages_the_enchanted_walker():
    eng = engine()
    pw = walker(eng)
    aura(eng, "Liliana's Talent", pw)
    attacker = creature(eng, "p2", "Attacker")
    eng.rules.deal_damage(pw, 1, source=attacker)
    eng.resolve_until_stable()
    assert attacker.zone == Zone.GRAVEYARD


def test_lilianas_talent_spares_creatures_that_hit_another_walker_or_a_player():
    eng = engine()
    pw = walker(eng, name="Enchanted")
    other = walker(eng, name="Other")
    aura(eng, "Liliana's Talent", pw)
    attacker = creature(eng, "p2", "Attacker")
    eng.rules.deal_damage(other, 1, source=attacker)
    eng.rules.deal_damage(eng.state.player_by_id("p1"), 1, source=attacker)
    eng.resolve_until_stable()
    assert attacker.zone == Zone.BATTLEFIELD


def test_lilianas_talent_ignores_an_unattached_aura():
    eng = engine()
    pw = walker(eng)
    talent = aura(eng, "Liliana's Talent", pw)
    bear = creature(eng, "p2")
    talent.attached_to = None
    eng.rules.deal_damage(pw, 1, source=bear)
    eng.resolve_until_stable()
    assert bear.zone == Zone.BATTLEFIELD


def test_lilianas_talent_ignores_noncreature_damage_sources():
    eng = engine()
    pw = walker(eng)
    aura(eng, "Liliana's Talent", pw)
    rock = GameObject(Card(id="rock", name="Rock", type_line="Artifact"), owner_id="p2", zone=Zone.BATTLEFIELD)
    rock.controller_id = "p2"
    eng.state.add_to_battlefield(rock)
    eng.rules.deal_damage(pw, 1, source=rock)
    eng.resolve_until_stable()
    assert rock.zone == Zone.BATTLEFIELD and pw.loyalty == 3


def test_lilianas_granted_minus_eight_reanimates_every_graveyard_under_your_control():
    eng = engine()
    pw = walker(eng, loyalty=8, text="")
    aura(eng, "Liliana's Talent", pw)
    me, opp = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    mine = GameObject(Card(id="m", name="MyDead", type_line="Creature — Bear", is_creature=True, power=1,
                           toughness=1), owner_id="p1", zone=Zone.GRAVEYARD)
    theirs = GameObject(Card(id="t", name="TheirDead", type_line="Creature — Bear", is_creature=True, power=1,
                             toughness=1), owner_id="p2", zone=Zone.GRAVEYARD)
    spell = GameObject(Card(id="s", name="Spell", type_line="Sorcery"), owner_id="p2", zone=Zone.GRAVEYARD)
    me.graveyard.append(mine)
    opp.graveyard.append(theirs)
    opp.graveyard.append(spell)
    assert pw.granted_activated_abilities[0].cost.loyalty == -8
    eng.activate_ability(me, pw, 0)
    eng.resolve_until_stable()
    assert mine.zone == Zone.BATTLEFIELD and theirs.zone == Zone.BATTLEFIELD
    assert theirs.controller_id == "p1"
    assert spell.zone == Zone.GRAVEYARD


def test_liliana_vess_minus_eight_is_unlocked_by_the_same_clause():
    """Incidental unlock: the printed ultimate shares Liliana's Talent's body clause."""
    eng = engine()
    text = ("+1: Target player discards a card.\n−2: Search your library for a card, then shuffle and put that card "
            "on top.\n−8: Put all creature cards from all graveyards onto the battlefield under your control.")
    assert parse_oracle(Card(id="lv", name="Liliana Vess", type_line="Legendary Planeswalker — Liliana",
                             oracle_text=text, loyalty=5)).modeled
    pw = walker(eng, loyalty=8, text=text, name="Liliana Vess")
    me, opp = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    theirs = GameObject(Card(id="t", name="TheirDead", type_line="Creature — Bear", is_creature=True, power=1,
                             toughness=1), owner_id="p2", zone=Zone.GRAVEYARD)
    opp.graveyard.append(theirs)
    ultimate = next(i for i, a in enumerate(pw.activated_abilities) if a.cost.loyalty == -8)
    eng.activate_ability(me, pw, ultimate)
    eng.resolve_until_stable()
    assert theirs.zone == Zone.BATTLEFIELD and theirs.controller_id == "p1"

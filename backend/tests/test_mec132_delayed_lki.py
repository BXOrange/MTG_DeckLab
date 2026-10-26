"""MEC-132 — delayed end-of-combat effects on captured or departed objects, executed on the real engine.

RULE 603.7c: the objects a delayed triggered ability refers to are fixed when it is created. RULE 608.2h: damage a
source deals is read from its last known information, so it still happens when the source has left the battlefield.
RULE 400.7: a captured object that left and came back is a new object the delayed ability no longer names.
RULE 509.1a / 510.2: the block relation and the combat-damage event name the "other" creature.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase

from tests.test_par202_end_of_combat import (
    _advance_to, _alive, _attack, _block_only, _creature, _end_of_combat, _engine, _parse,
)

OGRE = "Whenever ~ blocks or becomes blocked by a creature, ~ deals 1 damage to that creature at end of combat."
VANGUARD = "When ~ blocks, at end of combat, destroy it and all creatures it blocked this turn."
ELEMENTAL = "When ~ attacks or blocks, at end of combat, sacrifice it and it deals 5 damage to you."
SOSUKE = "Whenever a Warrior you control deals combat damage to a creature, destroy that creature at end of combat."
SIMIC = (
    '{1}{G}: Until end of turn, target creature with a +1/+1 counter on it gains "Whenever ~ deals combat damage '
    'to a creature, destroy that creature at end of combat."'
)
BASILISK = "Whenever ~ deals combat damage to a creature, destroy that creature at end of combat."
TOUGH = 9  # survives any combat damage in these scenarios, so only the delayed effect can remove a creature


def _named(name):
    return CardDatabase(DB_PATH).get_card(name)


def _life(eng, pid="p1"):
    return eng.state.player_by_id(pid).life


# ---------------------------------------------------------------------------
# Parse shape
# ---------------------------------------------------------------------------


def _delayed(oracle):
    result = _parse(oracle)
    assert result.modeled, oracle
    spec = next(s for s in result.specs if s.ability_kind == "triggered")
    assert spec.effects[0].type == "create_delayed_trigger"
    return spec.effects[0].params


def test_ogre_captures_the_far_side_creature_and_deals_damage_by_lki():
    params = _delayed(OGRE)
    assert params["capture"] == "trigger_related" and params["step"] == "end_combat"
    assert params["effects"] == [{"type": "damage_specific", "params": {"amount": 1}}]


def test_vanguard_captures_itself_and_what_it_blocked():
    params = _delayed(VANGUARD)
    assert params["capture"] == "source_and_blocked"
    assert params["effects"] == [{"type": "destroy_specific", "params": {}}]


def test_time_elemental_sacrifices_by_control_and_damages_its_controller():
    params = _delayed(ELEMENTAL)
    assert params["capture"] == "self"
    assert params["effects"][0] == {"type": "sacrifice_specific", "params": {"controlled_only": True}}
    assert params["effects"][1]["type"] == "damage"


@pytest.mark.parametrize("oracle", [SOSUKE, BASILISK])
def test_damaged_creature_riders_capture_the_event_recipient(oracle):
    params = _delayed(oracle)
    assert params["capture"] == "trigger_subject" and params["trigger_event_key"] == "target_id"


@pytest.mark.parametrize(
    "oracle",
    [
        # no block to name the far side
        "Whenever ~ attacks, ~ deals 1 damage to that creature at end of combat.",
        # an attached host's "it" is not the Aura/Equipment that carries the ability
        "Whenever enchanted creature blocks or becomes blocked by a creature, it deals 1 damage to that creature at "
        "end of combat.",
        # an ambiguous "it" under a group recipient head could be either creature
        "Whenever a Warrior you control deals combat damage to a creature, destroy it at end of combat.",
        # the comma-form body keeps to self-bound effects
        "When ~ attacks, at end of combat, draw a card.",
    ],
)
def test_unmodeled_shapes_stay_unclaimed(oracle):
    assert _parse(oracle).modeled is False


@pytest.mark.parametrize(
    "name",
    ["Defiant Vanguard", "Sawtooth Ogre", "Sosuke, Son of Seshiro", "Simic Basilisk", "Lowland Basilisk",
     "Ohran Viper", "Serpentine Basilisk", "Stone-Tongue Basilisk"],
)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


# ---------------------------------------------------------------------------
# Sawtooth Ogre
# ---------------------------------------------------------------------------


def test_ogre_blocking_damages_the_attacker_it_blocked_at_end_of_combat():
    eng = _engine()
    attacker = _creature(eng, "Attacker", "p1", toughness=TOUGH, power=0)
    ogre = _creature(eng, "Ogre", "p2", OGRE, power=0, toughness=TOUGH)
    _block_only(eng, ogre, attacker)
    eng.resolve_until_stable()
    assert attacker.damage_marked == 0  # the trigger only created the delayed ability
    _end_of_combat(eng)
    assert attacker.damage_marked == 1
    assert not eng.state.delayed_triggers  # one-shot


def test_ogre_becoming_blocked_damages_the_blocker():
    eng = _engine()
    ogre = _creature(eng, "Ogre", "p1", OGRE, power=0, toughness=TOUGH)
    blocker = _creature(eng, "Blocker", "p2", power=0, toughness=TOUGH)
    _block_only(eng, blocker, ogre)
    _end_of_combat(eng)
    assert blocker.damage_marked == 1 and ogre.damage_marked == 0


def test_ogre_still_deals_the_damage_after_it_died_in_combat():
    # RULE 608.2h: "the damage happens even if this card is not on the battlefield at the end of combat".
    eng = _engine()
    attacker = _creature(eng, "Attacker", "p1", power=3, toughness=TOUGH)
    ogre = _creature(eng, "Ogre", "p2", OGRE, power=0, toughness=3)
    _block_only(eng, ogre, attacker)
    eng.resolve_until_stable()  # the block trigger resolves in the declare blockers step, creating the delayed ability
    _advance_to(eng, "end_combat")
    assert not _alive(eng, ogre)  # the three damage killed it
    eng.resolve_until_stable()
    assert attacker.damage_marked == 1  # the Ogre's own 0 combat damage plus the delayed 1


def test_ogre_damage_does_nothing_to_a_creature_that_left_and_came_back():
    # RULE 400.7: the blinked attacker is a new object the delayed ability never captured.
    eng = _engine()
    attacker = _creature(eng, "Attacker", "p1", power=0, toughness=TOUGH)
    ogre = _creature(eng, "Ogre", "p2", OGRE, power=0, toughness=TOUGH)
    _block_only(eng, ogre, attacker)
    eng.resolve_until_stable()
    eng.rules.blink(attacker)
    _end_of_combat(eng)
    assert attacker.damage_marked == 0


def test_ogre_with_the_far_side_gone_does_not_crash():
    eng = _engine()
    attacker = _creature(eng, "Attacker", "p1", power=5, toughness=TOUGH)
    ogre = _creature(eng, "Ogre", "p2", OGRE, power=0, toughness=TOUGH)
    _block_only(eng, ogre, attacker)
    eng.resolve_until_stable()
    eng.rules.put_into_graveyard(attacker)
    _end_of_combat(eng)
    assert _alive(eng, ogre)


# ---------------------------------------------------------------------------
# Defiant Vanguard
# ---------------------------------------------------------------------------


def test_vanguard_and_the_creature_it_blocked_are_destroyed_at_end_of_combat():
    eng = _engine()
    attacker = _creature(eng, "Attacker", "p1", toughness=TOUGH, power=0)
    bystander = _creature(eng, "Bystander", "p1")
    vanguard = _creature(eng, "Vanguard", "p2", VANGUARD, power=0, toughness=TOUGH)
    _attack(eng, [attacker], [(vanguard, attacker)])
    eng.resolve_until_stable()
    assert _alive(eng, vanguard) and _alive(eng, attacker)
    _end_of_combat(eng)
    assert not _alive(eng, vanguard) and not _alive(eng, attacker)
    assert _alive(eng, bystander)
    assert not eng.state.delayed_triggers


def test_vanguard_that_died_in_combat_still_takes_the_creature_it_blocked_with_it():
    # RULE 603.7c / 608.2h: the set was fixed when the ability resolved, so the Vanguard's death does not unmake it.
    eng = _engine()
    attacker = _creature(eng, "Attacker", "p1", power=3, toughness=TOUGH)
    vanguard = _creature(eng, "Vanguard", "p2", VANGUARD, power=0, toughness=3)
    _attack(eng, [attacker], [(vanguard, attacker)])
    eng.resolve_until_stable()  # the block trigger resolves before combat damage kills the Vanguard
    _end_of_combat(eng)
    assert not _alive(eng, vanguard) and not _alive(eng, attacker)


def test_vanguard_leaves_a_blocked_creature_that_was_blinked_alone():
    # RULE 400.7: the blinked attacker is a new object; only the Vanguard itself is destroyed.
    eng = _engine()
    attacker = _creature(eng, "Attacker", "p1", power=0, toughness=TOUGH)
    vanguard = _creature(eng, "Vanguard", "p2", VANGUARD, power=0, toughness=TOUGH)
    _attack(eng, [attacker], [(vanguard, attacker)])
    eng.resolve_until_stable()
    eng.rules.blink(attacker)
    _end_of_combat(eng)
    assert not _alive(eng, vanguard) and _alive(eng, attacker)


def test_vanguard_that_blinked_is_a_new_object_and_survives():
    eng = _engine()
    attacker = _creature(eng, "Attacker", "p1", power=0, toughness=TOUGH)
    vanguard = _creature(eng, "Vanguard", "p2", VANGUARD, power=0, toughness=TOUGH)
    _attack(eng, [attacker], [(vanguard, attacker)])
    eng.resolve_until_stable()
    eng.rules.blink(vanguard)
    _end_of_combat(eng)
    assert _alive(eng, vanguard)
    assert not _alive(eng, attacker)  # the attacker it blocked is still named and destroyed


# ---------------------------------------------------------------------------
# Time Elemental
# ---------------------------------------------------------------------------


def test_time_elemental_is_sacrificed_and_hurts_its_controller_at_end_of_combat():
    eng = _engine()
    elemental = _creature(eng, "Elemental", "p1", ELEMENTAL, toughness=TOUGH)
    _attack(eng, [elemental])
    eng.resolve_until_stable()
    assert _alive(eng, elemental) and _life(eng) == 20
    _end_of_combat(eng)
    assert not _alive(eng, elemental) and _life(eng) == 15
    assert not eng.state.delayed_triggers


def test_time_elemental_blocking_does_the_same():
    eng = _engine()
    attacker = _creature(eng, "Attacker", "p1", power=0, toughness=TOUGH)
    elemental = _creature(eng, "Elemental", "p2", ELEMENTAL, power=0, toughness=TOUGH)
    _block_only(eng, elemental, attacker)
    _end_of_combat(eng)
    assert not _alive(eng, elemental) and _life(eng, "p2") == 15


def test_time_elemental_that_died_in_combat_still_deals_its_damage():
    # RULE 608.2h: the sacrifice finds nothing, the damage is dealt by last known information.
    eng = _engine()
    elemental = _creature(eng, "Elemental", "p1", ELEMENTAL, power=1, toughness=1)
    blocker = _creature(eng, "Blocker", "p2", power=4, toughness=TOUGH)
    _attack(eng, [elemental], [(blocker, elemental)])
    _end_of_combat(eng)
    assert not _alive(eng, elemental) and _life(eng) == 15


def test_time_elemental_stolen_before_end_of_combat_is_not_sacrificed_but_still_damages():
    # Ruling 2007-09-16: "you can't sacrifice it. However, it will still deal 5 damage to you."
    eng = _engine()
    elemental = _creature(eng, "Elemental", "p1", ELEMENTAL, toughness=TOUGH)
    _attack(eng, [elemental])
    eng.resolve_until_stable()
    elemental.controller_id = "p2"
    _end_of_combat(eng)
    assert _alive(eng, elemental) and _life(eng) == 15


def test_time_elemental_that_blinked_is_a_new_object_and_is_not_sacrificed():
    eng = _engine()
    elemental = _creature(eng, "Elemental", "p1", ELEMENTAL, toughness=TOUGH)
    _attack(eng, [elemental])
    eng.resolve_until_stable()
    eng.rules.blink(elemental)
    _end_of_combat(eng)
    assert _alive(eng, elemental) and _life(eng) == 15


# ---------------------------------------------------------------------------
# Sosuke / the Basilisks / Simic Basilisk
# ---------------------------------------------------------------------------


def test_sosuke_destroys_the_creature_a_warrior_dealt_combat_damage_to_but_not_the_warrior():
    eng = _engine()
    _creature(eng, "Sosuke", "p1", SOSUKE, types="Legendary Creature — Human Samurai", power=0, toughness=TOUGH)
    warrior = _creature(eng, "Warrior", "p1", types="Creature — Human Warrior", power=1, toughness=TOUGH)
    victim = _creature(eng, "Victim", "p2", power=0, toughness=TOUGH)
    _attack(eng, [warrior], [(victim, warrior)])
    _advance_to(eng, "combat_damage")
    eng.resolve_until_stable()  # the damage trigger resolves in the combat damage step
    assert _alive(eng, victim)  # destruction waits for end of combat
    _end_of_combat(eng)
    assert not _alive(eng, victim) and _alive(eng, warrior)
    assert not eng.state.delayed_triggers


def test_sosuke_ignores_a_non_warrior_and_damage_to_a_player():
    eng = _engine()
    _creature(eng, "Sosuke", "p1", SOSUKE, types="Legendary Creature — Human Samurai", power=0, toughness=TOUGH)
    bear = _creature(eng, "Bear", "p1", power=1, toughness=TOUGH)
    warrior = _creature(eng, "Warrior", "p1", types="Creature — Human Warrior", power=1, toughness=TOUGH)
    victim = _creature(eng, "Victim", "p2", power=0, toughness=TOUGH)
    _attack(eng, [bear, warrior], [(victim, bear)])  # the Warrior is unblocked: damage to the player
    _end_of_combat(eng)
    assert _alive(eng, victim) and _alive(eng, bear) and _alive(eng, warrior)


def test_sosuke_victim_that_blinked_is_a_new_object_and_survives():
    eng = _engine()
    _creature(eng, "Sosuke", "p1", SOSUKE, types="Legendary Creature — Human Samurai", power=0, toughness=TOUGH)
    warrior = _creature(eng, "Warrior", "p1", types="Creature — Human Warrior", power=1, toughness=TOUGH)
    victim = _creature(eng, "Victim", "p2", power=0, toughness=TOUGH)
    _attack(eng, [warrior], [(victim, warrior)])
    _advance_to(eng, "combat_damage")
    eng.resolve_until_stable()
    eng.rules.blink(victim)
    _end_of_combat(eng)
    assert _alive(eng, victim)


def test_basilisk_destroys_what_it_damaged_not_itself():
    # Regression: this wording used to capture the source and destroy the Basilisk itself.
    eng = _engine()
    basilisk = _creature(eng, "Basilisk", "p1", BASILISK, power=1, toughness=TOUGH)
    victim = _creature(eng, "Victim", "p2", power=0, toughness=TOUGH)
    _attack(eng, [basilisk], [(victim, basilisk)])
    _end_of_combat(eng)
    assert _alive(eng, basilisk) and not _alive(eng, victim)


def test_simic_basilisk_grants_the_rider_until_end_of_turn_to_a_creature_with_a_counter():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    simic = _creature(eng, "Simic", "p1", SIMIC, power=0, toughness=TOUGH)
    fighter = _creature(eng, "Fighter", "p1", power=1, toughness=TOUGH)
    fighter.counters["+1/+1"] = 1
    victim = _creature(eng, "Victim", "p2", power=0, toughness=TOUGH)
    _advance_to(eng, "main1")
    p1.mana_pool.add_many({"G": 1, "C": 1})
    eng.activate_ability(p1, simic, 0, targets=[fighter])
    eng.resolve_until_stable()
    _attack(eng, [fighter], [(victim, fighter)])
    _end_of_combat(eng)
    assert _alive(eng, fighter) and not _alive(eng, victim)


def test_simic_basilisk_cannot_target_a_creature_without_a_counter():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    simic = _creature(eng, "Simic", "p1", SIMIC, power=0, toughness=TOUGH)
    plain = _creature(eng, "Plain", "p1", power=1, toughness=TOUGH)
    _advance_to(eng, "main1")
    p1.mana_pool.add_many({"G": 1, "C": 1})
    with pytest.raises(Exception):
        eng.activate_ability(p1, simic, 0, targets=[plain])

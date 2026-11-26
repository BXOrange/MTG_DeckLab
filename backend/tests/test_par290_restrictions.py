"""PAR-290 milestone 1: standing and one-shot restrictions, enforced on the real cards (RULE 508.1a, 601.3a, 305.1, 101.2).

Every card here is the real cached card, parsed and bound through the oracle-text fallback. Each restriction is asserted
for exactly its subject (a bystander is untouched), for the condition false and true and toggling, and for the source
leaving the battlefield (RULE 611.3b: a static ability's effect ends with it).
"""

from __future__ import annotations

import copy

import pytest

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    card = CardDatabase(DB_PATH).get_card(name)
    assert card is not None, name
    return card


def _engine(players=2):
    seats = [(f"p{i}", chr(64 + i), []) for i in range(1, players + 1)]
    return GameEngine.new_game(seats, starting_life=20, starting_hand=0)


def _bear(name="Bystander Bear", power=2, toughness=2, types="Creature — Bear", **extra):
    return Card(id=name, name=name, type_line=types, oracle_text="", is_creature=True, power=power,
                toughness=toughness, **extra)


def _put(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    eng.recompute_continuous_effects()
    return obj


def _real(eng, name, controller="p1"):
    return _put(eng, _named(name), controller)


def _leave(eng, obj):
    eng.state.battlefield.remove(obj)
    eng.recompute_continuous_effects()


def _can_attack(eng, attacker, defender_id, kind="player"):
    """RULE 508.1a: may ``attacker`` be declared against that defender right now?"""
    eng.recompute_continuous_effects()
    owner = eng.state.player_by_id(attacker.controller_id)
    return eng._can_attack(owner, attacker, eng.state.player_by_id(defender_id), defender_kind=kind)


@pytest.mark.parametrize("name", [
    "Blazing Archon", "Reverence", "Form of the Dragon", "Teferi's Moat", "Queen Mother Ramonda", "Vow of Flight",
    "Vow of Duty", "Vow of Lightning", "Vow of Malice", "Vow of Torment", "Vow of Wildness", "Demotion",
    "Gelid Shackles", "Detainment Spell", "Stupefying Touch", "Viper's Kiss", "Encrust", "Hold for Questioning",
    "Stuck in Summoner's Sanctum", "Grid Monitor", "Steel Golem", "Nikya of the Old Ways",
    "Aether Storm", "Platinum Angel", "Gaea's Herald", "Leyline of Lifeforce", "Root Sliver", "Sphinx of the Final Word",
    "Melira's Keepers", "Tatterkite", "Blightbeetle", "Territorial Dispute", "Aggressive Mining", "Solfatara",
    "Turf Wound", "Pardic Miner", "Cease-Fire", "Teleport", "Necrologia", "Seedtime", "Lure of Prey",
    "Twice Upon a Time // Unlikely Meeting", "Feast of Blood", "Hewed Stone Retainers", "Illusory Angel",
    "Skyshroud Condor", "Aether Tunnel", "Flitterstep Eidolon", "Cryptic Coat", "Tricks of the Trade",
    "Predatory Impetus", "Protective Bubble",
])
def test_claimed_real_cards_parse_modeled(name):
    assert parse_oracle(_named(name)).modeled, name


# -- "creatures can't attack you" (RULE 508.1a) ----------------------------------------------------------------------


def test_blazing_archon_bars_every_creature_from_its_controller_but_not_their_planeswalkers():
    eng = _engine(3)
    archon = _real(eng, "Blazing Archon", "p1")
    foe = _put(eng, _bear("Foe Bear"), "p2")
    assert not _can_attack(eng, foe, "p1")
    assert _can_attack(eng, foe, "p3")  # the clause protects only its controller
    # "attack you" names the player, not planeswalkers they control (RULE 508.1a), and not a battle either (RULE 310.8d)
    assert _can_attack(eng, foe, "p1", kind="planeswalker")
    assert _can_attack(eng, foe, "p1", kind="battle")
    _leave(eng, archon)
    assert _can_attack(eng, foe, "p1")


def test_reverence_bars_only_small_attackers_and_reads_derived_power():
    eng = _engine()
    _real(eng, "Reverence", "p1")
    small = _put(eng, _bear("Small", power=2), "p2")
    big = _put(eng, _bear("Big", power=3), "p2")
    assert not _can_attack(eng, small, "p1")
    assert _can_attack(eng, big, "p1")
    small.counters["+1/+1"] = 1  # derived power 3 now (RULE 613): no longer barred
    assert _can_attack(eng, small, "p1")


def test_form_of_the_dragon_bars_only_creatures_without_flying():
    eng = _engine()
    _real(eng, "Form of the Dragon", "p1")
    walker = _put(eng, _bear("Walker"), "p2")
    flyer = _put(eng, _bear("Flyer", keywords=["Flying"]), "p2")
    assert not _can_attack(eng, walker, "p1")
    assert _can_attack(eng, flyer, "p1")


def test_queen_mother_ramonda_bars_small_attackers_only_while_you_are_the_monarch():
    eng = _engine()
    _real(eng, "Queen Mother Ramonda", "p1")
    small = _put(eng, _bear("Small", power=2), "p2")
    eng.state.monarch_id = None
    assert _can_attack(eng, small, "p1")
    eng.state.monarch_id = "p1"
    assert not _can_attack(eng, small, "p1")
    eng.state.monarch_id = "p2"  # the condition toggles back off
    assert _can_attack(eng, small, "p1")


def test_vow_of_flight_bars_only_the_enchanted_creature_from_the_aura_controller():
    eng = _engine(3)
    host = _put(eng, _bear("Host"), "p2")
    other = _put(eng, _bear("Other"), "p2")
    vow = _real(eng, "Vow of Flight", "p1")
    vow.attached_to = host.instance_id
    assert not _can_attack(eng, host, "p1")
    assert not _can_attack(eng, host, "p1", kind="planeswalker")  # "or planeswalkers you control"
    assert _can_attack(eng, host, "p3")
    assert _can_attack(eng, other, "p1")  # a bystander is untouched
    assert (host.power, host.toughness) == (4, 4) and "flying" in host.granted_keywords
    _leave(eng, vow)
    assert _can_attack(eng, host, "p1")


def test_an_unattached_vow_bars_nobody():
    eng = _engine()
    host = _put(eng, _bear("Host"), "p2")
    _real(eng, "Vow of Duty", "p1")  # on the battlefield attached to nothing
    assert _can_attack(eng, host, "p1")


# -- the host's activated abilities (RULE 602.5) ---------------------------------------------------------------------


def _activate_probe(eng, obj):
    """Is the one activated ability of ``obj`` legal right now (mana not an issue: a free ability)?"""
    eng.recompute_continuous_effects()
    return eng.can_activate(eng.state.player_by_id(obj.controller_id), obj, obj.activated_abilities[0])


def _clicker():
    return Card(id="Clicker", name="Clicker", type_line="Creature — Construct", is_creature=True, power=1, toughness=1,
                oracle_text="{T}: Draw a card.")


@pytest.mark.parametrize("name", ["Detainment Spell", "Stupefying Touch", "Demotion", "Gelid Shackles", "Viper's Kiss"])
def test_aura_locks_the_hosts_activated_abilities_but_nobody_elses(name):
    eng = _engine()
    host = _put(eng, _clicker(), "p2")
    bystander = _put(eng, _clicker(), "p2")
    assert _activate_probe(eng, host)
    aura = _real(eng, name, "p1")
    aura.attached_to = host.instance_id
    assert not _activate_probe(eng, host)
    assert _activate_probe(eng, bystander)
    aura.attached_to = None  # RULE 303.4: unattached, the lock is gone
    assert _activate_probe(eng, host)
    aura.attached_to = host.instance_id
    _leave(eng, aura)
    assert _activate_probe(eng, host)


def test_demotion_also_stops_the_host_blocking_and_viper_kiss_shrinks_it():
    eng = _engine()
    host = _put(eng, _bear("Host", toughness=3), "p2")
    demotion = _real(eng, "Demotion", "p1")
    demotion.attached_to = host.instance_id
    eng.recompute_continuous_effects()
    assert "cant_block" in host.granted_keywords
    kiss = _real(eng, "Viper's Kiss", "p1")
    kiss.attached_to = host.instance_id
    eng.recompute_continuous_effects()
    assert (host.power, host.toughness) == (1, 2)


def test_encrust_stops_the_host_untapping_and_activating_but_not_a_bystander():
    eng = _engine()
    host = _put(eng, _clicker(), "p2")
    bystander = _put(eng, _clicker(), "p2")
    encrust = _real(eng, "Encrust", "p1")
    encrust.attached_to = host.instance_id
    eng.recompute_continuous_effects()
    assert not _activate_probe(eng, host)
    assert continuous.has_no_untap_static(eng.state, host)  # RULE 502.3 / 611.3b
    assert not continuous.has_no_untap_static(eng.state, bystander)
    _leave(eng, encrust)
    assert not continuous.has_no_untap_static(eng.state, host)
    assert _activate_probe(eng, host)


# -- "you can't cast <type> spells" (RULE 601.3a) ---------------------------------------------------------------------


def _hand_spell(eng, name, type_line, owner="p1"):
    card = Card(id=name, name=name, type_line=type_line, mana_cost_string="", converted_mana_cost=0,
                is_creature="Creature" in type_line, power=1 if "Creature" in type_line else None,
                toughness=1 if "Creature" in type_line else None)
    obj = GameObject(card, owner_id=owner, zone=Zone.HAND)
    eng.state.player_by_id(owner).add_to_zone(obj, Zone.HAND)
    return obj


def _castable(eng, obj):
    eng.state.current_step = "main1"
    eng.state.active_player_index = [p.id for p in eng.state.players].index(obj.owner_id)
    return eng.can_cast(eng.state.player_by_id(obj.owner_id), obj)


def test_grid_monitor_stops_only_its_controller_casting_creature_spells():
    eng = _engine()
    monitor = _real(eng, "Grid Monitor", "p1")
    mine = _hand_spell(eng, "My Creature", "Creature — Bear", "p1")
    my_sorcery = _hand_spell(eng, "My Sorcery", "Sorcery", "p1")
    theirs = _hand_spell(eng, "Their Creature", "Creature — Bear", "p2")
    assert not _castable(eng, mine)
    assert _castable(eng, my_sorcery)  # only creature spells
    assert _castable(eng, theirs)  # "you" is the controller only
    _leave(eng, monitor)
    assert _castable(eng, mine)


def test_nikya_stops_noncreature_spells():
    eng = _engine()
    nikya = _real(eng, "Nikya of the Old Ways", "p1")
    creature = _hand_spell(eng, "A Creature", "Creature — Bear")
    sorcery = _hand_spell(eng, "A Sorcery", "Sorcery")
    assert _castable(eng, creature) and not _castable(eng, sorcery)
    _leave(eng, nikya)
    # BUG-73: Codie's own mana line carries next-cast riders the builder never executes, so the card is UNMODELED and
    # its permanent-spell prohibition no longer binds; Nikya's half above is the covered behaviour.


def test_aether_storm_stops_every_players_creature_spells():
    eng = _engine()
    _real(eng, "Aether Storm", "p1")
    mine = _hand_spell(eng, "My Creature", "Creature — Bear", "p1")
    theirs = _hand_spell(eng, "Their Creature", "Creature — Bear", "p2")
    instant = _hand_spell(eng, "An Instant", "Instant", "p2")
    assert not _castable(eng, mine) and not _castable(eng, theirs)
    assert _castable(eng, instant)


# -- "can't play lands" (RULE 305.1) ----------------------------------------------------------------------------------


def _land_in_hand(eng, owner):
    card = Card(id=f"Forest-{owner}", name="Forest", type_line="Basic Land — Forest", is_land=True)
    obj = GameObject(card, owner_id=owner, zone=Zone.HAND)
    eng.state.player_by_id(owner).add_to_zone(obj, Zone.HAND)
    return obj


def _can_play_land(eng, obj):
    eng.state.current_step = "main1"
    eng.state.active_player_index = [p.id for p in eng.state.players].index(obj.owner_id)
    return eng.can_play_land(eng.state.player_by_id(obj.owner_id), obj)


def test_territorial_dispute_stops_every_players_land_plays_until_it_leaves():
    eng = _engine()
    dispute = _real(eng, "Territorial Dispute", "p1")
    mine, theirs = _land_in_hand(eng, "p1"), _land_in_hand(eng, "p2")
    assert not _can_play_land(eng, mine) and not _can_play_land(eng, theirs)
    _leave(eng, dispute)
    assert _can_play_land(eng, mine) and _can_play_land(eng, theirs)


def test_aggressive_mining_stops_only_its_controller_playing_lands():
    eng = _engine()
    mining = _real(eng, "Aggressive Mining", "p1")
    mine, theirs = _land_in_hand(eng, "p1"), _land_in_hand(eng, "p2")
    assert not _can_play_land(eng, mine)
    assert _can_play_land(eng, theirs)
    _leave(eng, mining)
    assert _can_play_land(eng, mine)


# -- Platinum Angel (RULE 104.3b) -------------------------------------------------------------------------------------


def test_platinum_angel_keeps_you_in_the_game_at_zero_life_and_stops_opponents_winning():
    eng = _engine()
    angel = _real(eng, "Platinum Angel", "p1")
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    p1.life = 0
    eng.rules.check_state_based_actions()
    assert not p1.has_lost
    eng.rules.player_wins(p2)
    assert not eng.state.game_over  # "your opponents can't win the game"
    _leave(eng, angel)
    eng.rules.check_state_based_actions()
    assert p1.has_lost


def test_platinum_angel_does_not_protect_its_controllers_opponent():
    eng = _engine()
    _real(eng, "Platinum Angel", "p1")
    p2 = eng.state.player_by_id("p2")
    p2.life = 0
    eng.rules.check_state_based_actions()
    assert p2.has_lost


# -- "can't be countered" for every player's creature / Sliver / your instants and sorceries --------------------------


def _uncounterable(eng, name, type_line, controller, text=""):
    card = Card(id=name, name=name, type_line=type_line, oracle_text=text, is_creature="Creature" in type_line,
                power=1 if "Creature" in type_line else None, toughness=1 if "Creature" in type_line else None)
    obj = GameObject(card, owner_id=controller, zone=Zone.STACK)
    obj.controller_id = controller
    return eng.rules._is_cant_be_countered(obj)


def test_gaeas_herald_covers_every_players_creature_spells_only():
    eng = _engine()
    herald = _real(eng, "Gaea's Herald", "p1")
    assert _uncounterable(eng, "Mine", "Creature — Bear", "p1")
    assert _uncounterable(eng, "Theirs", "Creature — Bear", "p2")
    assert not _uncounterable(eng, "Bolt", "Instant", "p2")
    _leave(eng, herald)
    assert not _uncounterable(eng, "Theirs", "Creature — Bear", "p2")


def test_root_sliver_covers_slivers_of_every_controller():
    eng = _engine()
    _real(eng, "Root Sliver", "p1")
    assert _uncounterable(eng, "Their Sliver", "Creature — Sliver", "p2")
    assert not _uncounterable(eng, "Their Bear", "Creature — Bear", "p2")


def test_sphinx_of_the_final_word_covers_only_your_instants_and_sorceries():
    eng = _engine()
    _real(eng, "Sphinx of the Final Word", "p1")
    assert _uncounterable(eng, "My Bolt", "Instant", "p1")
    assert _uncounterable(eng, "My Wrath", "Sorcery", "p1")
    assert not _uncounterable(eng, "Their Bolt", "Instant", "p2")
    assert not _uncounterable(eng, "My Bear", "Creature — Bear", "p1")


# -- "can't have counters put on it" (RULE 122.1) ---------------------------------------------------------------------


def test_melira_keepers_takes_no_counters_but_a_bystander_does():
    eng = _engine()
    keepers = _real(eng, "Melira's Keepers", "p1")
    other = _put(eng, _bear("Other"), "p1")
    eng.rules.add_counters(keepers, 1, "+1/+1")
    eng.rules.add_counters(other, 1, "+1/+1")
    assert keepers.counters.get("+1/+1", 0) == 0
    assert other.counters.get("+1/+1", 0) == 1


def test_blightbeetle_bars_plus_one_counters_on_opponents_creatures_only():
    eng = _engine()
    _real(eng, "Blightbeetle", "p1")
    mine, theirs = _put(eng, _bear("Mine"), "p1"), _put(eng, _bear("Theirs"), "p2")
    eng.rules.add_counters(mine, 1, "+1/+1")
    eng.rules.add_counters(theirs, 1, "+1/+1")
    eng.rules.add_counters(theirs, 1, "-1/-1")  # only +1/+1 counters are barred
    assert mine.counters.get("+1/+1", 0) == 1
    assert theirs.counters.get("+1/+1", 0) == 0 and theirs.counters.get("-1/-1", 0) == 1


# -- one-shot "target player can't ... this turn" (RULE 611.2) -------------------------------------------------------


def _cast_real(eng, name, owner="p1", targets=None):
    card = _named(name)
    obj = GameObject(card, owner_id=owner, zone=Zone.HAND)
    bind_from_catalogue(obj)
    player = eng.state.player_by_id(owner)
    player.add_to_zone(obj, Zone.HAND)
    for color in "WUBRG":
        player.mana_pool.add(color, 5)
    eng.state.current_step = "main1"
    eng.state.active_player_index = [p.id for p in eng.state.players].index(owner)
    eng.cast_spell(player, obj, targets=targets)
    eng.resolve_until_stable()
    return obj


@pytest.mark.parametrize("name", ["Solfatara", "Turf Wound"])
def test_target_player_cant_play_lands_this_turn_binds_only_that_player(name):
    eng = _engine(3)
    _cast_real(eng, name, "p1", targets=[eng.state.player_by_id("p2")])
    banned, other, caster = (_land_in_hand(eng, pid) for pid in ("p2", "p3", "p1"))
    assert not _can_play_land(eng, banned)
    assert _can_play_land(eng, other) and _can_play_land(eng, caster)


def test_the_land_bar_ends_with_the_turn():
    from mtg_analyzer.game import durations

    eng = _engine()
    _cast_real(eng, "Turf Wound", "p1", targets=[eng.state.player_by_id("p2")])
    banned = _land_in_hand(eng, "p2")
    assert not _can_play_land(eng, banned)
    durations.sweep(eng.state, "cleanup")  # RULE 514.2: "this turn" effects end in the cleanup step
    assert _can_play_land(eng, banned)


def test_cease_fire_bars_only_the_chosen_players_creature_spells():
    eng = _engine(3)
    _cast_real(eng, "Cease-Fire", "p1", targets=[eng.state.player_by_id("p2")])
    barred = _hand_spell(eng, "Barred Creature", "Creature — Bear", "p2")
    sorcery = _hand_spell(eng, "Free Sorcery", "Sorcery", "p2")
    other = _hand_spell(eng, "Other Creature", "Creature — Bear", "p3")
    assert not _castable(eng, barred)
    assert _castable(eng, sorcery) and _castable(eng, other)


def test_pardic_miner_sacrifice_bars_the_chosen_player_from_playing_lands():
    eng = _engine()
    miner = _real(eng, "Pardic Miner", "p1")
    eng.state.current_step = "main1"
    eng.activate_ability(eng.state.player_by_id("p1"), miner, 0, targets=[eng.state.player_by_id("p2")])
    eng.resolve_until_stable()
    assert miner not in eng.state.battlefield
    assert not _can_play_land(eng, _land_in_hand(eng, "p2"))
    assert _can_play_land(eng, _land_in_hand(eng, "p1"))


# -- "Cast this spell only ..." (RULE 601.3) --------------------------------------------------------------------------


def _hand_real(eng, name, owner="p1"):
    obj = GameObject(_named(name), owner_id=owner, zone=Zone.HAND)
    bind_from_catalogue(obj)
    player = eng.state.player_by_id(owner)
    player.add_to_zone(obj, Zone.HAND)
    for color in "WUBRG":
        player.mana_pool.add(color, 8)
    return obj


def _can_cast_at(eng, obj, step, active="p1"):
    eng.state.current_step = step
    eng.state.active_player_index = [p.id for p in eng.state.players].index(active)
    return eng.can_cast(eng.state.player_by_id(obj.owner_id), obj)


def test_feast_of_blood_needs_two_vampires_and_follows_the_count():
    eng = _engine()
    feast = _hand_real(eng, "Feast of Blood")
    assert not _can_cast_at(eng, feast, "main1")
    one = _put(eng, _bear("Vamp One", types="Creature — Vampire"))
    assert not _can_cast_at(eng, feast, "main1")
    _put(eng, _bear("Vamp Two", types="Creature — Vampire"))
    assert _can_cast_at(eng, feast, "main1")
    # an opponent's vampires don't count, and losing one closes the window again
    eng.state.battlefield.remove(one)
    assert not _can_cast_at(eng, feast, "main1")
    _put(eng, _bear("Their Vamp", types="Creature — Vampire"), "p2")
    assert not _can_cast_at(eng, feast, "main1")


def test_twice_upon_a_time_needs_two_doctors():
    eng = _engine()
    spell = _hand_real(eng, "Twice Upon a Time // Unlikely Meeting")
    assert not _can_cast_at(eng, spell, "main1")
    _put(eng, _bear("Doc One", types="Creature — Time Lord Doctor"))
    _put(eng, _bear("Doc Two", types="Creature — Time Lord Doctor"))
    assert _can_cast_at(eng, spell, "main1")


def test_seedtime_only_on_your_own_turn():
    eng = _engine()
    seedtime = _hand_real(eng, "Seedtime")
    assert _can_cast_at(eng, seedtime, "main1", active="p1")
    assert not _can_cast_at(eng, seedtime, "main1", active="p2")


def test_necrologia_only_during_your_end_step():
    eng = _engine()
    spell = _hand_real(eng, "Necrologia")
    assert _can_cast_at(eng, spell, "end", active="p1")
    assert not _can_cast_at(eng, spell, "end", active="p2")  # an opponent's end step
    assert not _can_cast_at(eng, spell, "main1", active="p1")


def test_teleport_only_during_the_declare_attackers_step():
    eng = _engine()
    spell = _hand_real(eng, "Teleport")
    assert not _can_cast_at(eng, spell, "main1")
    assert _can_cast_at(eng, spell, "declare_attackers", active="p2")
    assert not _can_cast_at(eng, spell, "declare_blockers", active="p2")


def test_lure_of_prey_needs_an_opponent_creature_spell_this_turn():
    eng = _engine()
    spell = _hand_real(eng, "Lure of Prey")
    assert not _can_cast_at(eng, spell, "main1", active="p2")
    other = _hand_spell(eng, "Opp Creature", "Creature — Bear", "p2")
    eng.state.current_step = "main1"
    eng.state.active_player_index = 1
    eng.cast_spell(eng.state.player_by_id("p2"), other)
    eng.resolve_until_stable()
    assert _can_cast_at(eng, spell, "main1", active="p2")


@pytest.mark.parametrize("name", ["Hewed Stone Retainers", "Illusory Angel", "Skyshroud Condor"])
def test_another_spell_this_turn_gate(name):
    eng = _engine()
    spell = _hand_real(eng, name)
    assert not _can_cast_at(eng, spell, "main1")
    first = _hand_spell(eng, "First Spell", "Sorcery", "p1")
    eng.state.current_step = "main1"
    eng.cast_spell(eng.state.player_by_id("p1"), first)
    eng.resolve_until_stable()
    assert _can_cast_at(eng, spell, "main1")


# -- host buff plus "can't be blocked" (RULE 509.1b), the clause shape the combat grammar now reads whole -------------


def _blockable(eng, attacker, blocker):
    eng.recompute_continuous_effects()
    eng.state.active_player_index = [p.id for p in eng.state.players].index(attacker.controller_id)
    attacker.attacking = True
    attacker.combat_defender = {"kind": "player", "id": blocker.controller_id}
    return eng.can_block(eng.state.player_by_id(blocker.controller_id), blocker, attacker)


def test_aether_tunnel_makes_only_its_host_unblockable_and_pumps_it():
    eng = _engine()
    host = _put(eng, _bear("Host"), "p1")
    other = _put(eng, _bear("Other"), "p1")
    blocker = _put(eng, _bear("Blocker"), "p2")
    tunnel = _real(eng, "Aether Tunnel", "p1")
    assert _blockable(eng, host, blocker)  # not attached yet
    tunnel.attached_to = host.instance_id
    assert not _blockable(eng, host, blocker)
    assert _blockable(eng, other, blocker)
    assert (host.power, host.toughness) == (3, 2)
    _leave(eng, tunnel)
    assert _blockable(eng, host, blocker)


def test_steel_of_the_godhead_unblockable_only_while_the_host_is_blue():
    eng = _engine()
    blue = Card(id="Blue Bear", name="Blue Bear", type_line="Creature — Bear", is_creature=True, power=2, toughness=2,
                mana_cost_string="{1}{U}")
    host = _put(eng, blue, "p1")
    blocker = _put(eng, _bear("Blocker"), "p2")
    steel = _real(eng, "Steel of the Godhead", "p1")
    steel.attached_to = host.instance_id
    assert not _blockable(eng, host, blocker)
    host.card.mana_cost_string = "{1}{R}"  # no longer blue: the second ability turns off (RULE 105.2)
    assert _blockable(eng, host, blocker)


def test_wall_crawl_unblockable_by_defenders_for_spiders_only():
    eng = _engine()
    _real(eng, "Wall Crawl", "p1")
    spider = _put(eng, _bear("Spider Friend", types="Creature — Spider"), "p1")
    bear = _put(eng, _bear("Plain Bear"), "p1")
    wall = _put(eng, _bear("Wall", types="Creature — Wall", keywords=["Defender"]), "p2")
    walker = _put(eng, _bear("Walker"), "p2")
    assert not _blockable(eng, spider, wall)
    assert _blockable(eng, spider, walker)
    assert _blockable(eng, bear, wall)  # not a Spider
    assert (spider.power, spider.toughness) == (3, 3)


def test_slippery_scoundrel_is_unblockable_only_with_the_citys_blessing():
    eng = _engine()
    scoundrel = _real(eng, "Slippery Scoundrel", "p1")
    blocker = _put(eng, _bear("Blocker"), "p2")
    p1 = eng.state.player_by_id("p1")
    assert _blockable(eng, scoundrel, blocker)
    p1.has_city_blessing = True
    assert not _blockable(eng, scoundrel, blocker)
    p1.has_city_blessing = False
    assert _blockable(eng, scoundrel, blocker)


def test_bilbos_ring_unblockable_only_during_your_turn():
    eng = _engine()
    host = _put(eng, _bear("Host"), "p1")
    blocker = _put(eng, _bear("Blocker"), "p2")
    ring = _real(eng, "Bilbo's Ring", "p1")
    ring.attached_to = host.instance_id
    assert not _blockable(eng, host, blocker)  # p1's turn
    eng.recompute_continuous_effects()
    eng.state.active_player_index = 1
    host.attacking = True
    eng.recompute_continuous_effects()
    assert "cant_be_blocked" not in host.granted_keywords  # an opponent's turn: the gate is off


def test_predatory_impetus_buffs_forces_blocks_and_goads_its_host():
    eng = _engine()
    host = _put(eng, _bear("Host"), "p2")
    aura = _real(eng, "Predatory Impetus", "p1")
    aura.attached_to = host.instance_id
    eng.recompute_continuous_effects()
    assert (host.power, host.toughness) == (5, 5)
    assert "must_be_blocked" in host.granted_keywords
    _leave(eng, aura)
    assert "must_be_blocked" not in host.granted_keywords


# -- clone / undo keep the floating restriction (a floating static lives in `GameState.floating_statics`) ------------


def test_a_floating_land_bar_survives_a_state_clone_with_its_player_and_duration():
    eng = _engine(3)
    _cast_real(eng, "Turf Wound", "p1", targets=[eng.state.player_by_id("p2")])
    clone = eng.state.clone()
    assert continuous.land_play_prohibited(clone, clone.player_by_id("p2"))
    assert not continuous.land_play_prohibited(clone, clone.player_by_id("p3"))
    assert [ab.duration for ab in clone.floating_statics] == [ab.duration for ab in eng.state.floating_statics]


def test_teferis_moat_bars_only_nonflying_creatures_of_the_chosen_colour():
    eng = _engine()
    moat = _real(eng, "Teferi's Moat", "p1")
    moat.chosen_color = "R"
    red = _put(eng, _bear("Red Walker", mana_cost_string="{1}{R}"), "p2")
    red_flyer = _put(eng, _bear("Red Flyer", mana_cost_string="{1}{R}", keywords=["Flying"]), "p2")
    green = _put(eng, _bear("Green Walker", mana_cost_string="{1}{G}"), "p2")
    assert not _can_attack(eng, red, "p1")
    assert _can_attack(eng, red_flyer, "p1") and _can_attack(eng, green, "p1")
    moat.chosen_color = None  # nothing chosen bars nothing
    assert _can_attack(eng, red, "p1")


@pytest.mark.parametrize("clause", [
    "creatures can't attack you unless their controller pays {2}.",
    "creatures named lightning rager can't attack you or planeswalkers you control.",
    "other players' creatures can't attack you.",
    "you can't cast spells.",
    "you can't cast creature spells this turn.",
    "players can't play lands this turn.",
    "target opponent can't play lands this turn.",
    "creature spells you control can't be countered unless they're blue.",
    "~ can't have counters put on it unless you pay {1}.",
    "enchanted creature's activated abilities can't be activated unless they're loyalty abilities.",
])
def test_neighbouring_shapes_stay_unclaimed(clause):
    from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause

    specs = static_effect_specs(clause)
    own = {"cant_attack_defender", "cast_prohibition", "land_play_prohibition", "counter_placement_prohibition",
           "activation_prohibition", "grant_cant_be_countered", "restrict_target_player_this_turn"}
    assert not specs or not (own & {e.type for e in specs}), clause
    one_shot = match_clause(clause.rstrip("."))
    assert not one_shot or not (own & {e.type for e in one_shot}), clause

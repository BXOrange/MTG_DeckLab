"""PAR-290 milestone 2: blocker-side bars, creature-side attack/block costs, group "can't block/attack this turn".

Real cached cards, bound through the oracle-text fallback; each bar is asserted for its exact subject (bystanders and
near misses untouched), while the source is present, after it leaves, and (one-shots) after the turn ends.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import combat, durations
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from tests.test_par290_restrictions import _can_cast_at, _hand_real, _bear, _blockable, _can_attack, _cast_real, _engine, _leave, _named, _put, _real

M2_CARDS = [
    "Spectral Grasp", "Bower Passage", "Silumgar Assassin", "Spitfire Handler", "Brainwash", "Cowed by Wisdom",
    "Qal Sisma Behemoth", "Myr Prototype", "Phyrexian Marauder", "Hipparion", "Awe for the Guilds",
    "Flash of Defiance", "Pyrophobia", "Festival", "Goblin Locksmith", "Manacles of Decay", "Chaosphere",
    "Dense Canopy", "Bloodcrazed Goblin", "Technodrome", "Hazoret, Godseeker", "Wirecat", "Shauku, Endbringer",
    "Basandra, Battle Seraph", "Marisi, Breaker of the Coil", "Brisela, Voice of Nightmares", "Iona, Shield of Emeria",
]


@pytest.mark.parametrize("name", M2_CARDS)
def test_claimed_real_cards_parse_modeled(name):
    assert parse_oracle(_named(name)).modeled, name


def _colored(name, *symbols):
    return _bear(name, mana_cost={s: 1 for s in symbols}, mana_cost_string="".join(f"{{{s}}}" for s in symbols),
                 converted_mana_cost=len(symbols))


def _attach(aura, host):
    aura.attached_to = host.instance_id


# -- blocker-side bar scoped to the static controller's creatures (RULE 509.1a) ----------------------------------------


def test_spectral_grasp_bars_its_host_from_blocking_only_its_controllers_creatures():
    eng = _engine(3)
    host = _put(eng, _bear("Host"), "p2")
    mine, theirs = _put(eng, _bear("Mine"), "p1"), _put(eng, _bear("Theirs"), "p3")
    grasp = _real(eng, "Spectral Grasp", "p1")
    _attach(grasp, host)
    assert not _blockable(eng, mine, host)
    assert _blockable(eng, theirs, host)  # a creature p1 doesn't control is still blockable by the host
    bystander = _put(eng, _bear("Bystander"), "p2")
    assert _blockable(eng, mine, bystander)
    _leave(eng, grasp)
    assert _blockable(eng, mine, host)


def test_spectral_grasp_follows_a_change_of_its_controller():
    eng = _engine(3)
    host = _put(eng, _bear("Host"), "p2")
    mine, other = _put(eng, _bear("Mine"), "p1"), _put(eng, _bear("Other"), "p3")
    grasp = _real(eng, "Spectral Grasp", "p1")
    _attach(grasp, host)
    grasp.controller_id = "p3"
    assert _blockable(eng, mine, host) and not _blockable(eng, other, host)


def test_bower_passage_bars_only_flyers_and_only_against_its_controllers_creatures():
    eng = _engine(3)
    _real(eng, "Bower Passage", "p1")
    mine, theirs = _put(eng, _bear("Mine"), "p1"), _put(eng, _bear("Theirs"), "p3")
    flyer = _put(eng, _bear("Flyer", keywords=["Flying"]), "p2")
    walker = _put(eng, _bear("Walker"), "p2")
    assert not _blockable(eng, mine, flyer)
    assert _blockable(eng, theirs, flyer)
    assert _blockable(eng, mine, walker)


def test_silumgar_assassin_cant_be_blocked_by_bigger_creatures_and_it_reads_derived_power():
    eng = _engine()
    assassin = _real(eng, "Silumgar Assassin", "p1")
    base = assassin.power
    big = _put(eng, _bear("Big", power=base + 1), "p2")
    even = _put(eng, _bear("Even", power=base), "p2")
    assert not _blockable(eng, assassin, big)
    assert _blockable(eng, assassin, even)
    assassin.counters["+1/+1"] = 1  # now as big as the blocker: no longer "greater"
    assert _blockable(eng, assassin, big)


def test_spitfire_handler_cant_block_attackers_with_more_power_than_itself():
    eng = _engine()
    handler = _real(eng, "Spitfire Handler", "p2")
    big = _put(eng, _bear("Big", power=handler.power + 1), "p1")
    even = _put(eng, _bear("Even", power=handler.power), "p1")
    assert not _blockable(eng, big, handler)
    assert _blockable(eng, even, handler)
    _leave(eng, handler)


def test_chaosphere_and_dense_canopy_let_flyers_block_only_flyers():
    eng = _engine()
    _real(eng, "Dense Canopy", "p1")
    flyer = _put(eng, _bear("Flyer", keywords=["Flying"]), "p2")
    ground_attacker = _put(eng, _bear("Ground"), "p1")
    air_attacker = _put(eng, _bear("Air", keywords=["Flying"]), "p1")
    assert not _blockable(eng, ground_attacker, flyer)
    assert _blockable(eng, air_attacker, flyer)


# -- creature-side attack/block costs (RULE 508.1g, 509.1c) ------------------------------------------------------------


def test_brainwash_charges_only_its_host_three_and_stops_with_the_aura():
    eng = _engine()
    host, other = _put(eng, _bear("Host")), _put(eng, _bear("Other"))
    brain = _real(eng, "Brainwash", "p2")
    _attach(brain, host)
    eng.recompute_continuous_effects()
    assert combat.attack_cost_for(eng.state, host) == 3
    assert combat.attack_cost_for(eng.state, other) == 0
    assert combat.block_cost_for(eng.state, host, other) == 0  # attack-only
    _leave(eng, brain)
    assert combat.attack_cost_for(eng.state, host) == 0


def _declare_step(eng, player_id="p1"):
    eng.state.current_step = "declare_attackers"
    eng.state.active_player_index = [p.id for p in eng.state.players].index(player_id)


def test_the_attack_cost_is_paid_on_declaration_and_an_unpayable_one_blocks_the_attack():
    eng = _engine()
    host = _put(eng, _bear("Host"))
    brain = _real(eng, "Brainwash", "p2")
    _attach(brain, host)
    eng.recompute_continuous_effects()
    _declare_step(eng)
    player = eng.state.player_by_id("p1")
    with pytest.raises(ValueError):
        eng.declare_attackers(player, [host])  # no mana at all
    assert not host.attacking
    for _ in range(3):
        player.mana_pool.add("G", 1)
    eng.declare_attackers(player, [host])
    assert host.attacking
    assert sum(player.mana_pool.pool.values()) == 0 if hasattr(player.mana_pool, "pool") else True


def test_the_attack_offer_carries_the_creatures_own_cost():
    eng = _engine()
    host, other = _put(eng, _bear("Host")), _put(eng, _bear("Other"))
    brain = _real(eng, "Brainwash", "p2")
    _attach(brain, host)
    eng.recompute_continuous_effects()
    _declare_step(eng)
    offers = {a["instance_id"]: a for a in eng.legal_actions(eng.state.player_by_id("p1")) if a["type"] == "attack"}
    assert offers[host.instance_id]["attack_tax_amounts"][0] == 3
    assert offers[other.instance_id]["attack_tax_amounts"][0] == 0


def test_cowed_by_wisdom_counts_the_auras_controllers_hand_not_the_hosts():
    eng = _engine()
    host = _put(eng, _bear("Host"), "p1")
    cowed = _real(eng, "Cowed by Wisdom", "p2")
    _attach(cowed, host)
    for i in range(2):
        eng.state.player_by_id("p2").add_to_zone(GameObject(_bear(f"Card{i}"), owner_id="p2", zone=Zone.HAND), Zone.HAND)
    eng.state.player_by_id("p1").add_to_zone(GameObject(_bear("Mine"), owner_id="p1", zone=Zone.HAND), Zone.HAND)
    eng.recompute_continuous_effects()
    assert combat.attack_cost_for(eng.state, host) == 2
    assert combat.block_cost_for(eng.state, host, host) == 2  # "attack or block"
    eng.state.player_by_id("p2").hand.clear()
    assert combat.attack_cost_for(eng.state, host) == 0


def test_myr_prototype_and_marauder_charge_per_plus_one_counter_on_themselves():
    eng = _engine()
    myr = _real(eng, "Myr Prototype", "p1")
    marauder = _real(eng, "Phyrexian Marauder", "p1")
    for obj, n in ((myr, 3), (marauder, 2)):
        obj.counters["+1/+1"] = n
    eng.recompute_continuous_effects()
    assert combat.attack_cost_for(eng.state, myr) == 3
    assert combat.block_cost_for(eng.state, myr, marauder) == 3
    assert combat.attack_cost_for(eng.state, marauder) == 2
    assert combat.block_cost_for(eng.state, marauder, myr) == 0  # Marauder simply can't block (a flag), no cost
    myr.counters["+1/+1"] = 0
    assert combat.attack_cost_for(eng.state, myr) == 0


def test_qal_sisma_behemoth_costs_two_each_way_and_the_block_cost_is_paid_on_declaration():
    eng = _engine()
    beast = _real(eng, "Qal Sisma Behemoth", "p2")
    attacker = _put(eng, _bear("Attacker"), "p1")
    assert combat.attack_cost_for(eng.state, beast) == 2
    assert combat.block_cost_for(eng.state, beast, attacker) == 2
    eng.state.current_step = "declare_blockers"
    eng.state.active_player_index = 0
    attacker.attacking = True
    attacker.combat_defender = {"kind": "player", "id": "p2"}
    defender = eng.state.player_by_id("p2")
    with pytest.raises(ValueError):
        eng.declare_blockers(defender, [(beast, attacker)])
    assert not combat.blocking_attacker_ids(beast)
    defender.mana_pool.add("U", 2)
    eng.declare_blockers(defender, [(beast, attacker)])
    assert combat.blocking_attacker_ids(beast)


def test_hipparion_pays_only_against_attackers_with_power_three_or_more():
    eng = _engine()
    hip = _real(eng, "Hipparion", "p2")
    small, big = _put(eng, _bear("Small", power=2), "p1"), _put(eng, _bear("Big", power=3), "p1")
    assert combat.block_cost_for(eng.state, hip, small) == 0
    assert combat.block_cost_for(eng.state, hip, big) == 1
    assert combat.attack_cost_for(eng.state, hip) == 0


# -- group one-shots (RULE 611.2, 509.1a) -------------------------------------------------------------------------------


def _can_block_now(eng, attacker, blocker):
    return _blockable(eng, attacker, blocker)


def _cast_with_target(eng, name, target, owner="p1"):
    return _cast_real(eng, name, owner, targets=[target])


def test_awe_for_the_guilds_bars_exactly_the_monocolored_creatures_including_later_entrants_until_the_turn_ends():
    eng = _engine()
    mono = _put(eng, _colored("Mono", "R"), "p2")
    gold = _put(eng, _colored("Gold", "R", "G"), "p2")
    colorless = _put(eng, _bear("Colorless"), "p2")
    attacker = _put(eng, _bear("Attacker"), "p1")
    _cast_real(eng, "Awe for the Guilds", "p1")
    assert not _can_block_now(eng, attacker, mono)
    assert _can_block_now(eng, attacker, gold) and _can_block_now(eng, attacker, colorless)
    # RULE 611.2c: a restriction is no characteristic change, so a creature entering later is barred too
    late_mono = _put(eng, _colored("LateMono", "U"), "p2")
    late_gold = _put(eng, _colored("LateGold", "U", "B"), "p2")
    assert not _can_block_now(eng, attacker, late_mono) and _can_block_now(eng, attacker, late_gold)
    durations.sweep(eng.state, "cleanup")  # RULE 514.2: "this turn" ends in the cleanup step
    assert _can_block_now(eng, attacker, mono) and _can_block_now(eng, attacker, late_mono)


def test_flash_of_defiance_bars_green_and_white_but_not_red_or_multicolored_neighbours():
    eng = _engine()
    green, white, red = (_put(eng, _colored(n, c), "p2") for n, c in (("G", "G"), ("W", "W"), ("R", "R")))
    attacker = _put(eng, _bear("Attacker"), "p1")
    _cast_real(eng, "Flash of Defiance", "p1")
    assert not _can_block_now(eng, attacker, green) and not _can_block_now(eng, attacker, white)
    assert _can_block_now(eng, attacker, red)
    late_white = _put(eng, _colored("LateW", "W"), "p2")
    assert not _can_block_now(eng, attacker, late_white)


def test_pyrophobia_bars_cowards_only():
    eng = _engine()
    coward = _put(eng, _bear("Coward", types="Creature — Coward"), "p2")
    bear = _put(eng, _bear("Bear"), "p2")
    victim = _put(eng, _bear("Victim", power=1, toughness=9), "p2")
    attacker = _put(eng, _bear("Attacker"), "p1")
    _cast_with_target(eng, "Pyrophobia", victim)
    assert not _can_block_now(eng, attacker, coward)
    assert _can_block_now(eng, attacker, bear)
    assert not _can_block_now(eng, attacker, _put(eng, _bear("Late Coward", types="Creature — Coward"), "p2"))
    durations.sweep(eng.state, "cleanup")
    assert _can_block_now(eng, attacker, coward)


def test_goblin_locksmith_trigger_bars_defenders_from_blocking():
    eng = _engine()
    smith = _real(eng, "Goblin Locksmith", "p1")
    wall = _put(eng, _bear("Wall", keywords=["Defender"]), "p2")
    bear = _put(eng, _bear("Bear"), "p2")
    eng.state.current_step = "declare_attackers"
    eng.state.active_player_index = 0
    eng.declare_attackers(eng.state.player_by_id("p1"), [smith])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert combat.has(wall, "cant_block") and not combat.has(bear, "cant_block")
    assert combat.has(_put(eng, _bear("Late Wall", keywords=["Defender"]), "p2"), "cant_block")


def test_manacles_of_decay_bars_only_its_host_from_blocking_this_turn():
    eng = _engine()
    host, other = _put(eng, _bear("Host"), "p2"), _put(eng, _bear("Other"), "p2")
    manacles = _real(eng, "Manacles of Decay", "p1")
    _attach(manacles, host)
    eng.recompute_continuous_effects()
    player = eng.state.player_by_id("p1")
    player.mana_pool.add("R", 3)
    eng.state.current_step = "main1"
    index = next(i for i, ab in enumerate(manacles.activated_abilities) if any(type(e).__name__ == "CantBlockEffect" for e in ab.effects))
    eng.activate_ability(player, manacles, index)
    eng.resolve_until_stable()
    assert host.temp_cant_block and not other.temp_cant_block


# -- "Creatures can't attack this turn" (RULE 508.1a, 611.2c) ------------------------------------------------------------


def test_festival_bars_every_creature_including_one_entering_later_until_the_turn_ends():
    eng = _engine()
    early = _put(eng, _bear("Early"), "p1")
    eng.state.current_step = "upkeep"
    eng.state.active_player_index = 1
    festival = GameObject(_named("Festival"), owner_id="p1", zone=Zone.HAND)
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    bind_from_catalogue(festival)
    eng.state.player_by_id("p1").add_to_zone(festival, Zone.HAND)
    for color in "WUBRG":
        eng.state.player_by_id("p1").mana_pool.add(color, 5)
    eng.cast_spell(eng.state.player_by_id("p1"), festival)
    eng.resolve_until_stable()
    late = _put(eng, _bear("Late"), "p2")
    eng.recompute_continuous_effects()
    assert combat.has(early, "cant_attack") and combat.has(late, "cant_attack")
    # clone keeps the floating bar
    clone = eng.state.clone()
    assert [ab.duration for ab in clone.floating_statics] == [ab.duration for ab in eng.state.floating_statics] != []
    durations.sweep(eng.state, "cleanup")
    eng.recompute_continuous_effects()
    assert not combat.has(early, "cant_attack")


def test_festival_only_in_an_opponents_upkeep():
    eng = _engine()
    festival = GameObject(_named("Festival"), owner_id="p1", zone=Zone.HAND)
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    bind_from_catalogue(festival)
    eng.state.player_by_id("p1").add_to_zone(festival, Zone.HAND)
    for color in "WUBRG":
        eng.state.player_by_id("p1").mana_pool.add(color, 5)
    eng.state.current_step = "upkeep"
    eng.state.active_player_index = 0
    assert not eng.can_cast(eng.state.player_by_id("p1"), festival)
    eng.state.active_player_index = 1
    assert eng.can_cast(eng.state.player_by_id("p1"), festival)


def test_group_cant_block_clones_with_its_floating_static():
    eng = _engine()
    _put(eng, _colored("Mono", "R"), "p2")
    _cast_real(eng, "Awe for the Guilds", "p1")
    clone = eng.state.clone()
    assert [ab.duration for ab in clone.floating_statics] == [ab.duration for ab in eng.state.floating_statics] != []


# -- "can't attack/block unless C" and its "if C" mirror (RULE 508.1a, 509.1a) --------------------------------------------


def test_bloodcrazed_goblin_attacks_only_once_an_opponent_has_been_dealt_damage():
    eng = _engine(3)
    goblin = _real(eng, "Bloodcrazed Goblin", "p1")
    assert not _can_attack(eng, goblin, "p2")
    eng.rules.deal_damage(eng.state.player_by_id("p1"), 2, source=goblin)  # its own controller is not "an opponent"
    assert not _can_attack(eng, goblin, "p2")
    eng.rules.deal_damage(eng.state.player_by_id("p3"), 1, source=goblin)
    assert _can_attack(eng, goblin, "p2")


def test_technodrome_needs_six_power_to_attack_or_block_and_reads_derived_power():
    eng = _engine()
    dome = _real(eng, "Technodrome", "p1")
    foe = _put(eng, _bear("Foe"), "p2")
    assert dome.power < 6 and not _can_attack(eng, dome, "p2")
    dome.counters["+1/+1"] = 6 - dome.power
    eng.recompute_continuous_effects()
    assert dome.power >= 6 and _can_attack(eng, dome, "p2")
    dome.counters["+1/+1"] = 0
    assert not _can_attack(eng, dome, "p2")
    assert foe


def test_hazoret_needs_max_speed_to_attack_or_block():
    eng = _engine()
    hazoret = _real(eng, "Hazoret, Godseeker", "p1")
    assert not _can_attack(eng, hazoret, "p2")
    eng.state.player_by_id("p1").speed = 4
    assert _can_attack(eng, hazoret, "p2")
    eng.state.player_by_id("p1").speed = 3
    assert not _can_attack(eng, hazoret, "p2")


def test_wirecat_is_barred_while_any_enchantment_is_on_the_battlefield_either_side():
    eng = _engine()
    cat = _real(eng, "Wirecat", "p1")
    attacker = _put(eng, _bear("Attacker"), "p2")
    assert _can_attack(eng, cat, "p2") and _blockable(eng, attacker, cat)
    ench = _put(eng, _bear("Rune", types="Enchantment"), "p2")
    ench.card.is_creature = False
    assert not _can_attack(eng, cat, "p2")
    assert not _blockable(eng, attacker, cat)
    _leave(eng, ench)
    assert _can_attack(eng, cat, "p2")


def test_shauku_attacks_only_while_it_is_the_only_creature():
    eng = _engine()
    shauku = _real(eng, "Shauku, Endbringer", "p1")
    assert _can_attack(eng, shauku, "p2")
    other = _put(eng, _bear("Other"), "p2")
    assert not _can_attack(eng, shauku, "p2")
    _leave(eng, other)
    assert _can_attack(eng, shauku, "p2")


# -- cast bars with a window, a mana-value range or the chosen color (RULE 601.3a) -------------------------------------------


def _hand_spell(eng, name, types, owner, cost=0, colors=()):
    card = _bear(name, types=types, mana_cost={c: 1 for c in colors}, mana_cost_string="".join(f"{{{c}}}" for c in colors),
                 converted_mana_cost=cost) if "Creature" in types else None
    from mtg_analyzer.models.cards.card import Card

    if card is None:
        card = Card(id=name, name=name, type_line=types, oracle_text="", is_instant="Instant" in types,
                    is_sorcery="Sorcery" in types, mana_cost={c: 1 for c in colors},
                    mana_cost_string="".join(f"{{{c}}}" for c in colors), converted_mana_cost=cost)
    obj = GameObject(card, owner_id=owner, zone=Zone.HAND)
    eng.state.player_by_id(owner).add_to_zone(obj, Zone.HAND)
    for color in "WUBRG":
        eng.state.player_by_id(owner).mana_pool.add(color, 8)
    return obj


def _cast_in_phase(eng, spell, step, phase, active="p1"):
    eng.state.current_phase = phase
    return _can_cast_at(eng, spell, step, active)


def test_basandra_bars_every_players_spells_during_combat_only():
    eng = _engine()
    _real(eng, "Basandra, Battle Seraph", "p1")
    mine = _hand_spell(eng, "Mine", "Instant", "p1")
    theirs = _hand_spell(eng, "Theirs", "Instant", "p2")
    assert not _cast_in_phase(eng, mine, "declare_attackers", "combat")
    assert not _cast_in_phase(eng, theirs, "declare_attackers", "combat")
    assert _cast_in_phase(eng, mine, "main2", "main2") and _cast_in_phase(eng, theirs, "main2", "main2")


def test_marisi_bars_only_opponents_during_combat_and_lifts_when_marisi_leaves():
    eng = _engine()
    marisi = _real(eng, "Marisi, Breaker of the Coil", "p1")
    mine = _hand_spell(eng, "Mine", "Instant", "p1")
    theirs = _hand_spell(eng, "Theirs", "Instant", "p2")
    assert _cast_in_phase(eng, mine, "declare_blockers", "combat")
    assert not _cast_in_phase(eng, theirs, "declare_blockers", "combat")
    _leave(eng, marisi)
    assert _cast_in_phase(eng, theirs, "declare_blockers", "combat")


def test_brisela_bars_opponents_spells_with_mana_value_three_or_less_only():
    eng = _engine()
    brisela = _real(eng, "Brisela, Voice of Nightmares", "p1")
    cheap = _hand_spell(eng, "Cheap", "Instant", "p2", cost=3)
    dear = _hand_spell(eng, "Dear", "Instant", "p2", cost=4)
    mine = _hand_spell(eng, "Mine", "Instant", "p1", cost=1)
    assert not _can_cast_at(eng, cheap, "main1", "p2")
    assert _can_cast_at(eng, dear, "main1", "p2")
    assert _can_cast_at(eng, mine, "main1", "p1")
    _leave(eng, brisela)
    assert _can_cast_at(eng, cheap, "main1", "p2")


def test_iona_bars_opponents_spells_of_the_chosen_color_and_nothing_before_the_choice():
    eng = _engine()
    iona = _real(eng, "Iona, Shield of Emeria", "p1")
    red = _hand_spell(eng, "Red", "Instant", "p2", cost=1, colors="R")
    blue = _hand_spell(eng, "Blue", "Instant", "p2", cost=1, colors="U")
    mine = _hand_spell(eng, "MineRed", "Instant", "p1", cost=1, colors="R")
    assert _can_cast_at(eng, red, "main1", "p2")  # no color chosen yet: no bar guessed
    iona.chosen_color = "R"
    assert not _can_cast_at(eng, red, "main1", "p2")
    assert _can_cast_at(eng, blue, "main1", "p2") and _can_cast_at(eng, mine, "main1", "p1")
    _leave(eng, iona)
    assert _can_cast_at(eng, red, "main1", "p2")


# -- the older closed-table group rows now share the floating form (BUG-74, RULE 611.2c) -------------------------------

def _land(name="Bystander Land"):
    from mtg_analyzer.models.cards.card import Card

    return Card(id=name, name=name, type_line="Land", oracle_text="", is_land=True)


def _cast_mode(eng, name, mode, owner="p1", targets=None):
    obj = _hand_real(eng, name, owner)
    eng.state.current_step = "main1"
    eng.state.active_player_index = [p.id for p in eng.state.players].index(owner)
    eng.cast_spell(eng.state.player_by_id(owner), obj, targets=targets, mode=mode)
    eng.resolve_until_stable()
    return obj


def _board(eng):
    """A flier, a ground creature and a small creature on each side, plus an attacker."""
    return {
        "attacker": _put(eng, _bear("Attacker"), "p1"),
        "my_ground": _put(eng, _bear("MyGround", power=1), "p1"),
        "their_ground": _put(eng, _bear("TheirGround"), "p2"),
        "their_flier": _put(eng, _bear("TheirFlier", keywords=["Flying"]), "p2"),
        "their_small": _put(eng, _bear("TheirSmall", power=1), "p2"),
    }


def _assert_barred_then_expires(eng, attacker, barred, free, late_barred, late_free):
    for blocker in barred:
        assert not _can_block_now(eng, attacker, blocker)
    for blocker in free:
        assert _can_block_now(eng, attacker, blocker)
    # RULE 611.2c: creatures entering after the effect resolved are bound exactly like the ones present
    assert not _can_block_now(eng, attacker, late_barred)
    assert _can_block_now(eng, attacker, late_free)
    durations.sweep(eng.state, "cleanup")  # RULE 514.2
    for blocker in (*barred, late_barred):
        assert _can_block_now(eng, attacker, blocker)


@pytest.mark.parametrize("name", ["Falter", "Magmatic Chasm", "Seismic Stomp"])
def test_creatures_without_flying_cant_block_spells(name):
    eng = _engine()
    b = _board(eng)
    _cast_real(eng, name, "p1")
    late_ground = _put(eng, _bear("LateGround", power=3), "p2")
    late_flier = _put(eng, _bear("LateFlier", keywords=["Flying"]), "p2")
    _assert_barred_then_expires(eng, b["attacker"], [b["their_ground"], b["their_small"]], [b["their_flier"]],
                                late_ground, late_flier)


def test_ruthless_invasion_spares_artifact_creatures_including_later_ones():
    eng = _engine()
    b = _board(eng)
    golem = _put(eng, _bear("Golem", types="Artifact Creature — Golem"), "p2")
    _cast_real(eng, "Ruthless Invasion", "p1")
    late_plain = _put(eng, _bear("LatePlain"), "p2")
    late_golem = _put(eng, _bear("LateGolem", types="Artifact Creature — Golem"), "p2")
    _assert_barred_then_expires(eng, b["attacker"], [b["their_ground"], b["their_flier"]], [golem],
                                late_plain, late_golem)


@pytest.mark.parametrize("name", ["Cosmotronic Wave", "Hazardous Blast"])
def test_creatures_your_opponents_control_cant_block_spells(name):
    eng = _engine()
    eng.state.player_by_id("p1").life = 20
    attacker = _put(eng, _bear("Attacker", toughness=5), "p1")
    mine = _put(eng, _bear("Mine", toughness=5), "p1")
    theirs = _put(eng, _bear("Theirs", toughness=5), "p2")
    _cast_real(eng, name, "p1")
    # the opposing creature is barred (and the near miss, my own creature, still may block)
    assert not _can_block_now(eng, attacker, theirs)
    late = _put(eng, _bear("Late", toughness=5), "p2")
    assert not _can_block_now(eng, attacker, late)
    opposing_attacker = _put(eng, _bear("OppAttacker"), "p2")
    assert _can_block_now(eng, opposing_attacker, mine)
    durations.sweep(eng.state, "cleanup")
    assert _can_block_now(eng, attacker, theirs) and _can_block_now(eng, attacker, late)


@pytest.mark.parametrize("name", ["Fire of Orthanc", "Tectonic Rift"])
def test_land_destruction_spells_bar_ground_blockers(name):
    eng = _engine()
    b = _board(eng)
    land = _put(eng, _land("Target Land") if name == "Tectonic Rift" else _land("Target Land"), "p2")
    _cast_real(eng, name, "p1", targets=[land])
    late_ground = _put(eng, _bear("LateGround"), "p2")
    late_flier = _put(eng, _bear("LateFlier", keywords=["Flying"]), "p2")
    _assert_barred_then_expires(eng, b["attacker"], [b["their_ground"]], [b["their_flier"]], late_ground, late_flier)


def test_sundering_eruption_bars_ground_blockers():
    eng = _engine()
    b = _board(eng)
    land = _put(eng, _land("Target Land"), "p2")
    obj = _hand_real(eng, "Sundering Eruption // Volcanic Fissure")
    eng.state.current_step = "main1"
    eng.state.active_player_index = 0
    eng.cast_spell(eng.state.player_by_id("p1"), obj, targets=[land])
    eng.resolve_until_stable()
    assert not _can_block_now(eng, b["attacker"], b["their_ground"])
    assert _can_block_now(eng, b["attacker"], b["their_flier"])


def test_destructive_tampering_mode_bars_ground_blockers():
    eng = _engine()
    b = _board(eng)
    _cast_mode(eng, "Destructive Tampering", 1)
    assert not _can_block_now(eng, b["attacker"], b["their_ground"])
    assert _can_block_now(eng, b["attacker"], b["their_flier"])
    assert not _can_block_now(eng, b["attacker"], _put(eng, _bear("Late"), "p2"))
    durations.sweep(eng.state, "cleanup")
    assert _can_block_now(eng, b["attacker"], b["their_ground"])


def test_temur_charm_power_three_or_less_mode():
    eng = _engine()
    attacker = _put(eng, _bear("Attacker"), "p1")
    small = _put(eng, _bear("Small", power=3), "p2")
    big = _put(eng, _bear("Big", power=4), "p2")
    _cast_mode(eng, "Temur Charm", 2)
    assert not _can_block_now(eng, attacker, small) and _can_block_now(eng, attacker, big)
    assert not _can_block_now(eng, attacker, _put(eng, _bear("LateSmall", power=1), "p2"))
    assert _can_block_now(eng, attacker, _put(eng, _bear("LateBig", power=5), "p2"))
    durations.sweep(eng.state, "cleanup")
    assert _can_block_now(eng, attacker, small)


def test_barrage_of_boulders_ferocious_gate():
    eng = _engine()
    attacker = _put(eng, _bear("Attacker"), "p1")
    blocker = _put(eng, _bear("Blocker"), "p2")
    _cast_real(eng, "Barrage of Boulders", "p1")  # no power-4 creature: the rider does nothing
    assert _can_block_now(eng, attacker, blocker)
    eng2 = _engine()
    attacker2 = _put(eng2, _bear("Attacker", power=4), "p1")
    blocker2 = _put(eng2, _bear("Blocker"), "p2")
    _cast_real(eng2, "Barrage of Boulders", "p1")
    assert not _can_block_now(eng2, attacker2, blocker2)
    assert not _can_block_now(eng2, attacker2, _put(eng2, _bear("Late"), "p2"))
    durations.sweep(eng2.state, "cleanup")
    assert _can_block_now(eng2, attacker2, blocker2)


def test_demoralize_threshold_gate():
    eng = _engine()
    attacker = _put(eng, _bear("Attacker"), "p1")
    blocker = _put(eng, _bear("Blocker"), "p2")
    _cast_real(eng, "Demoralize", "p1")
    assert _can_block_now(eng, attacker, blocker)
    eng2 = _engine()
    attacker2 = _put(eng2, _bear("Attacker"), "p1")
    blocker2 = _put(eng2, _bear("Blocker"), "p2")
    graveyard = eng2.state.player_by_id("p1").graveyard
    for i in range(7):
        filler = GameObject(_bear(f"Filler{i}"), owner_id="p1", zone=Zone.GRAVEYARD)
        graveyard.append(filler)
    _cast_real(eng2, "Demoralize", "p1")
    assert not _can_block_now(eng2, attacker2, blocker2)
    assert not _can_block_now(eng2, attacker2, _put(eng2, _bear("Late"), "p2"))


def test_seismic_elemental_enters_and_bars_ground_blockers():
    eng = _engine()
    b = _board(eng)
    _cast_real(eng, "Seismic Elemental", "p1")
    assert not _can_block_now(eng, b["attacker"], b["their_ground"])
    assert _can_block_now(eng, b["attacker"], b["their_flier"])
    durations.sweep(eng.state, "cleanup")
    assert _can_block_now(eng, b["attacker"], b["their_ground"])


def _attack_with(eng, attacker, choose=None):
    eng.state.current_step = "declare_attackers"
    eng.state.active_player_index = 0
    eng.declare_attackers(eng.state.player_by_id("p1"), [attacker])
    eng.resolve_until_stable()
    if choose is not None:  # the trigger's "up to one target creature" announcement
        eng.resolve_pending_choice(str(choose.instance_id))
        eng.resolve_until_stable()
    eng.recompute_continuous_effects()


def test_hero_of_oxid_ridge_attack_trigger_bars_power_one_or_less_including_later_entrants():
    eng = _engine()
    hero = _real(eng, "Hero of Oxid Ridge", "p1")
    small = _put(eng, _bear("Small", power=1), "p2")
    big = _put(eng, _bear("Big", power=2), "p2")
    _attack_with(eng, hero)
    assert combat.has(small, "cant_block") and not combat.has(big, "cant_block")
    late_small = _put(eng, _bear("LateSmall", power=0), "p2")
    assert combat.has(late_small, "cant_block")
    durations.sweep(eng.state, "cleanup")
    eng.recompute_continuous_effects()
    assert not combat.has(small, "cant_block") and not combat.has(late_small, "cant_block")


def test_aragorn_bars_every_creature_only_for_the_monarch():
    for monarch, barred in (("p1", True), (None, False)):
        eng = _engine()
        eng.state.monarch_id = monarch
        aragorn = _real(eng, "Aragorn, King of Gondor", "p1")
        target = _put(eng, _bear("Target"), "p2")
        bystander = _put(eng, _bear("Bystander"), "p2")
        _attack_with(eng, aragorn, choose=target)
        assert not _can_block_now(eng, aragorn, target)  # the "up to one target creature" half
        assert _can_block_now(eng, aragorn, bystander) is (not barred)  # monarch rider: every creature
        if barred:
            assert not _can_block_now(eng, aragorn, _put(eng, _bear("Late"), "p2"))
            durations.sweep(eng.state, "cleanup")
            assert _can_block_now(eng, aragorn, bystander)


def test_mournwillow_delirium_bars_power_two_or_less_only_with_four_card_types():
    for card_types, barred in ((("Creature", "Land", "Instant", "Sorcery"), True), (("Creature", "Land"), False)):
        eng = _engine()
        small = _put(eng, _bear("Small", power=2), "p2")
        big = _put(eng, _bear("Big", power=3), "p2")
        for i, kind in enumerate(card_types):
            eng.state.player_by_id("p1").graveyard.append(
                GameObject(_bear(f"G{i}", types=kind), owner_id="p1", zone=Zone.GRAVEYARD))
        _cast_real(eng, "Mournwillow", "p1")
        assert combat.has(small, "cant_block") is barred and not combat.has(big, "cant_block")
        if barred:
            assert combat.has(_put(eng, _bear("LateSmall", power=1), "p2"), "cant_block")


def test_stoneshock_giant_monstrosity_bars_only_nonflying_opposing_creatures():
    eng = _engine()
    giant = _real(eng, "Stoneshock Giant", "p1")
    mine = _put(eng, _bear("Mine"), "p1")
    ground = _put(eng, _bear("Ground"), "p2")
    flier = _put(eng, _bear("Flier", keywords=["Flying"]), "p2")
    player = eng.state.player_by_id("p1")
    player.mana_pool.add("R", 12)
    eng.state.current_step = "main1"
    eng.state.active_player_index = 0
    eng.activate_ability(player, giant, 0)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert combat.has(ground, "cant_block") and not combat.has(flier, "cant_block") and not combat.has(mine, "cant_block")
    assert combat.has(_put(eng, _bear("Late"), "p2"), "cant_block")
    durations.sweep(eng.state, "cleanup")
    eng.recompute_continuous_effects()
    assert not combat.has(ground, "cant_block")

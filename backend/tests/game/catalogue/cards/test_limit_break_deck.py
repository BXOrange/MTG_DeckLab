"""Gameplay regressions for the Limit Break (Final Fantasy Commander) deck batch."""
from mtg_analyzer.game import combat, continuous
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import (
    RICH, activate, answer, attack, card, cast, enter, filler, game, main_phase, named, pick_label, put_on_battlefield,
    stack_library, step,
)


def _equip(engine, equipment, creature, pool=None):
    engine.state.player_by_id("p1").mana_pool.add_many(pool or {"C": 7})
    activate(engine, equipment, 0, targets=[creature])


def test_champions_helm_gives_hexproof_only_to_a_legendary_host():
    engine = game()
    helm = card(engine, "Champion's Helm")
    legend = filler(engine, "Legend", type_line="Legendary Creature — Human", power=2, toughness=2)
    plain = filler(engine, "Plain", power=2, toughness=2)
    _equip(engine, helm, legend)
    assert legend.power == 4 and combat.has(legend, "hexproof")
    _equip(engine, helm, plain)
    assert plain.power == 4 and not combat.has(plain, "hexproof") and legend.power == 2


def test_heros_heirloom_gives_trample_and_haste_to_a_legendary_host():
    engine = game()
    heirloom = card(engine, "Hero's Heirloom")
    legend = filler(engine, "Legend", type_line="Legendary Creature — Human", power=2, toughness=2)
    _equip(engine, heirloom, legend)
    assert (legend.power, legend.toughness) == (4, 3)
    assert combat.has(legend, "trample") and combat.has(legend, "haste")


def test_mask_of_memory_loots_when_the_equipped_creature_connects():
    engine = game()
    mask = card(engine, "Mask of Memory")
    runner = filler(engine, "Runner", power=2, toughness=2)
    _equip(engine, mask, runner)
    me = engine.state.player_by_id("p1")
    hand = len(me.hand)
    engine.state.fire_event(GameEvent(EventType.DAMAGE, source_id=runner.instance_id, source_controller_id="p1",
                                      target_id="p2", is_player=True, combat=True, amount=2))
    engine.resolve_until_stable()
    answer(engine, lambda c: next((str(o["id"]) for o in c.get("options", []) if o.get("id") in ("yes", "do")), None))
    assert len(me.hand) == hand + 1  # +2 cards, -1 discard


def test_puresteel_paladin_makes_equip_free_with_three_artifacts():
    engine = game()
    helm = card(engine, "Champion's Helm")
    card(engine, "Puresteel Paladin")
    runner = filler(engine, "Runner", power=2, toughness=2)
    me = engine.state.player_by_id("p1")
    assert not me.mana_pool.total()
    for i in range(2):
        filler(engine, f"Rock {i}", type_line="Artifact")  # helm + 2 = three artifacts
    activate(engine, helm, 0, targets=[runner])  # no mana at all
    assert helm.attached_to == runner.instance_id


def test_puresteel_paladin_draws_when_an_equipment_enters():
    engine = game()
    card(engine, "Puresteel Paladin")
    me = engine.state.player_by_id("p1")
    hand = len(me.hand)
    put_on_battlefield(engine, "Hero's Heirloom")
    answer(engine, lambda c: next((str(o["id"]) for o in c.get("options", []) if o.get("id") in ("yes", "do")), None))
    assert len(me.hand) == hand + 1


def test_wrecking_ball_arm_sets_7_7_and_blocks_small_blockers_and_equips_legends_for_three():
    engine = game()
    arm = card(engine, "Wrecking Ball Arm")
    legend = filler(engine, "Legend", type_line="Legendary Creature — Human", power=2, toughness=2)
    plain = filler(engine, "Plain", power=2, toughness=2)
    me = engine.state.player_by_id("p1")
    costs = sorted(a.cost.raw for a in arm.activated_abilities)
    assert costs == ["{3}", "{7}"]  # "Equip legendary creature {3}" and the plain "Equip {7}"
    legend_equip = next(i for i, a in enumerate(arm.activated_abilities) if a.cost.raw == "{3}")
    me.mana_pool.add_many({"C": 3})
    activate(engine, arm, legend_equip, targets=[legend])
    assert (legend.power, legend.toughness) == (7, 7)
    small = filler(engine, "Small Blocker", power=2, toughness=2, player="p2")
    big = filler(engine, "Big Blocker", power=3, toughness=3, player="p2")
    p2 = engine.state.player_by_id("p2")
    legend.summoning_sick = False
    attack(engine, [legend])
    engine.state.current_step = "declare_blockers"
    assert not engine.can_block(p2, small, legend) and engine.can_block(p2, big, legend)
    assert plain.power == 2


def test_conformer_shuriken_taps_a_defender_and_copies_the_power_gap():
    engine = game()
    shuriken = card(engine, "Conformer Shuriken")
    runner = filler(engine, "Runner", power=2, toughness=2)
    giant = filler(engine, "Giant", power=5, toughness=5, player="p2")
    _equip(engine, shuriken, runner, {"C": 2})
    attack(engine, [runner])
    answer(engine, pick_label("Giant"))
    assert giant.tapped and runner.counters.get("+1/+1") == 3


def test_zack_fair_passes_counters_and_equipment_to_another_creature_when_sacrificed():
    engine = game()
    zack = card(engine, "Zack Fair", zone=Zone.HAND)
    cast(engine, zack)
    assert zack.counters.get("+1/+1") == 1
    helm = card(engine, "Hero's Heirloom")
    _equip(engine, helm, zack)
    ally = filler(engine, "Ally", power=1, toughness=1)
    engine.state.player_by_id("p1").mana_pool.add_many({"C": 1})
    activate(engine, zack, 0, targets=[ally])
    assert zack.zone == Zone.GRAVEYARD
    assert ally.counters.get("+1/+1") == 1 and "indestructible" in ally.temp_keywords
    assert helm.attached_to == ally.instance_id


def test_red_xiii_returns_an_aura_or_equipment_and_shares_vigilance_and_trample_with_modified_creatures():
    engine = game()
    gone = filler(engine, "Gone Blade", type_line="Artifact — Equipment", zone=Zone.GRAVEYARD)
    modified = filler(engine, "Marked", power=2, toughness=2)
    modified.add_counters("+1/+1", 1)
    plain = filler(engine, "Plain", power=2, toughness=2)
    put_on_battlefield(engine, "Red XIII, Proud Warrior")
    answer(engine, pick_label("Gone Blade"))
    assert gone.zone == Zone.HAND
    assert combat.has(modified, "vigilance") and combat.has(modified, "trample")
    assert not combat.has(plain, "vigilance")


def test_elena_returns_a_historic_card_and_grows_on_historic_spells():
    engine = game()
    relic = filler(engine, "Old Relic", type_line="Artifact", zone=Zone.GRAVEYARD)
    assassin = filler(engine, "Old Assassin", type_line="Legendary Creature — Human Assassin", power=1, toughness=1,
                      zone=Zone.GRAVEYARD)
    elena = put_on_battlefield(engine, "Elena, Turk Recruit")
    answer(engine, pick_label("Old Relic"))
    assert relic.zone == Zone.HAND and assassin.zone == Zone.GRAVEYARD
    spell = filler(engine, "Shiny Artifact", type_line="Artifact", mv=1, zone=Zone.HAND)
    cast(engine, spell)
    assert elena.counters.get("+1/+1") == 1


def test_cid_discounts_equipment_and_returns_them_from_the_graveyard():
    engine = game()
    cid = card(engine, "Cid, Freeflier Pilot")
    me = engine.state.player_by_id("p1")
    blade = filler(engine, "Blade", type_line="Artifact — Equipment", mv=3, zone=Zone.HAND)
    elf = filler(engine, "Elf", mv=3, zone=Zone.HAND)
    assert continuous.cost_reduction_for(engine.state, me, blade)[0] == 1
    assert continuous.cost_reduction_for(engine.state, me, elf)[0] == 0
    assert combat.has(cid, "flying")  # during your turn
    dead = filler(engine, "Dead Vehicle", type_line="Artifact — Vehicle", zone=Zone.GRAVEYARD)
    me.mana_pool.add_many({"C": 2})
    activate(engine, cid, 0, targets=[dead])
    assert dead.zone == Zone.HAND


def test_vincent_chaos_spreads_combat_damage_to_other_opponents_at_power_seven():
    engine = game(players=3)
    vincent = card(engine, "Vincent, Vengeful Atoner")
    vincent.add_counters("+1/+1", 4)  # 3/3 + 4 = 7/7
    engine.recompute_continuous_effects()
    assert vincent.power == 7
    engine.state.fire_event(GameEvent(EventType.DAMAGE, source_id=vincent.instance_id, source_controller_id="p1",
                                      target_id="p2", is_player=True, combat=True, amount=7))
    engine.resolve_until_stable()
    assert engine.state.player_by_id("p3").life == 13 and engine.state.player_by_id("p1").life == 20


def test_vincent_chaos_needs_power_seven():
    engine = game(players=3)
    vincent = card(engine, "Vincent, Vengeful Atoner")
    engine.state.fire_event(GameEvent(EventType.DAMAGE, source_id=vincent.instance_id, source_controller_id="p1",
                                      target_id="p2", is_player=True, combat=True, amount=3))
    engine.resolve_until_stable()
    assert engine.state.player_by_id("p3").life == 20


def test_heidegger_makes_soldiers_for_each_opponent_with_more_creatures():
    engine = game(players=3)
    card(engine, "Heidegger, Shinra Executive")
    for i in range(2):
        filler(engine, f"Their A{i}", power=1, toughness=1, player="p2")
    filler(engine, "Their B", power=1, toughness=1, player="p3")  # only p2 has more creatures than us (1 each vs 1)
    step(engine, "end")
    assert len(named(engine, "Soldier")) == 1


def test_hellkite_tyrant_steals_artifacts_and_wins_with_twenty():
    engine = game()
    tyrant = card(engine, "Hellkite Tyrant")
    rocks = [filler(engine, f"Their Rock {i}", type_line="Artifact", player="p2") for i in range(2)]
    engine.state.fire_event(GameEvent(EventType.DAMAGE, source_id=tyrant.instance_id, source_controller_id="p1",
                                      target_id="p2", is_player=True, combat=True, amount=6))
    engine.resolve_until_stable()
    assert all(r.controller_id == "p1" for r in rocks)
    for i in range(18):
        filler(engine, f"Rock {i}", type_line="Artifact")
    step(engine, "upkeep")
    assert engine.state.player_by_id("p1").has_won if hasattr(engine.state.player_by_id("p1"), "has_won") else engine.state.player_by_id("p2").has_lost


def test_clever_concealment_phases_out_chosen_permanents():
    engine = game()
    spell = card(engine, "Clever Concealment", zone=Zone.HAND)
    a = filler(engine, "A", power=1, toughness=1)
    b = filler(engine, "B", power=1, toughness=1)
    land = filler(engine, "Their Island", type_line="Basic Land — Island", player="p2")
    cast(engine, spell, groups=[[a, b]])
    assert a.phased_out and b.phased_out and not land.phased_out


def test_clouds_limit_break_tiers():
    engine = game()
    cross = card(engine, "Cloud's Limit Break", zone=Zone.HAND)
    tapped = filler(engine, "Tapped", power=2, toughness=2, player="p2")
    tapped.tapped = True
    untapped = filler(engine, "Untapped", power=2, toughness=2, player="p2")
    cast(engine, cross, targets=[tapped], mode=0)
    assert tapped.zone == Zone.GRAVEYARD and untapped.zone == Zone.BATTLEFIELD


def test_clouds_limit_break_omnislash_destroys_every_tapped_creature():
    engine = game()
    omni = card(engine, "Cloud's Limit Break", zone=Zone.HAND)
    mine = filler(engine, "Mine", power=2, toughness=2)
    mine.tapped = True
    theirs = filler(engine, "Theirs", power=2, toughness=2, player="p2")
    theirs.tapped = True
    spared = filler(engine, "Spared", power=2, toughness=2, player="p2")
    cast(engine, omni, mode=2)
    assert mine.zone == Zone.GRAVEYARD and theirs.zone == Zone.GRAVEYARD and spared.zone == Zone.BATTLEFIELD


def test_ultimate_magic_holy_protects_permanents_and_you_only_when_foretold():
    engine = game()
    holy = card(engine, "Ultimate Magic: Holy", zone=Zone.HAND)
    mine = filler(engine, "Mine", power=2, toughness=2)
    cast(engine, holy)
    assert "indestructible" in mine.temp_keywords
    me = engine.state.player_by_id("p1")
    life = me.life
    engine.rules.deal_damage(me, 3, source=filler(engine, "Bear", power=3, toughness=3, player="p2"))
    assert me.life == life - 3  # not cast from exile: no prevention


def test_ultimate_magic_meteor_deals_seven_to_each_creature():
    engine = game()
    meteor = card(engine, "Ultimate Magic: Meteor", zone=Zone.HAND)
    small = filler(engine, "Small", power=2, toughness=2)
    big = filler(engine, "Big", power=9, toughness=9, player="p2")
    cast(engine, meteor)
    assert small.zone == Zone.GRAVEYARD and big.zone == Zone.BATTLEFIELD and big.damage_marked == 7


def test_lifestreams_blessing_draws_for_the_greatest_power():
    engine = game()
    blessing = card(engine, "Lifestream's Blessing", zone=Zone.HAND)
    filler(engine, "Big", power=4, toughness=4)
    filler(engine, "Small", power=1, toughness=1)
    me = engine.state.player_by_id("p1")
    hand = len(me.hand) - 1  # the Blessing itself leaves the hand
    cast(engine, blessing)
    assert len(me.hand) == hand + 4


def test_unfinished_business_returns_a_creature_with_its_equipment():
    engine = game()
    spell = card(engine, "Unfinished Business", zone=Zone.HAND)
    hero = filler(engine, "Fallen Hero", power=2, toughness=2, zone=Zone.GRAVEYARD)
    blade = card(engine, "Champion's Helm", zone=Zone.GRAVEYARD)  # a real Equipment (it carries the equip keyword)
    cast(engine, spell, targets=[hero, blade])
    assert hero.zone == Zone.BATTLEFIELD and blade.zone == Zone.BATTLEFIELD
    assert blade.attached_to == hero.instance_id


def test_barret_wallace_burns_the_defender_per_equipped_creature():
    engine = game()
    barret = card(engine, "Barret Wallace")
    helm = card(engine, "Champion's Helm")
    ally = filler(engine, "Ally", power=1, toughness=1)
    _equip(engine, helm, ally)
    barret.summoning_sick = False
    attack(engine, [barret])
    assert engine.state.player_by_id("p2").life == 19  # one equipped creature (Ally)


def test_barret_avalanche_leader_makes_a_rebel_and_equips_it_at_combat():
    engine = game()
    card(engine, "Barret, Avalanche Leader")
    helm = put_on_battlefield(engine, "Champion's Helm")
    assert len(named(engine, "Rebel")) == 1
    step(engine, "begin_combat")
    answer(engine, pick_label("Champion's Helm", "Rebel"))
    answer(engine, pick_label("Rebel"))
    rebel = named(engine, "Rebel")[0]
    assert helm.attached_to == rebel.instance_id


def test_cloud_attaches_an_equipment_on_entering_and_draws_per_equipped_attacker():
    engine = game()
    helm = card(engine, "Champion's Helm")
    cloud = put_on_battlefield(engine, "Cloud, Ex-SOLDIER")
    answer(engine, pick_label("Champion's Helm"))
    assert helm.attached_to == cloud.instance_id
    me = engine.state.player_by_id("p1")
    hand = len(me.hand)
    attack(engine, [cloud])
    assert len(me.hand) == hand + 1
    assert len(named(engine, "Treasure")) == 0  # 3/3... Cloud is 4/4 +2 = 6 < 7


def test_avalanche_power_counts_opponents_artifacts_and_pings_artifact_activations():
    engine = game()
    avalanche = card(engine, "Avalanche of Sector 7")
    for i in range(3):
        filler(engine, f"Their Rock {i}", type_line="Artifact", player="p2")
    engine.recompute_continuous_effects()
    assert avalanche.power == 3
    engine.state.fire_event(GameEvent(EventType.ACTIVATED_ABILITY, player_id="p2", controller_id="p2", instance_id=0,
                                      object_types=["artifact"]))
    engine.resolve_until_stable()
    assert engine.state.player_by_id("p2").life == 19


def test_furious_rise_exiles_a_card_each_end_step_and_only_the_latest_stays_playable():
    engine = game()
    card(engine, "Furious Rise")
    filler(engine, "Big", power=4, toughness=4)
    first = filler(engine, "First Card", type_line="Sorcery", mv=2, zone=Zone.LIBRARY)
    second = filler(engine, "Second Card", type_line="Sorcery", mv=2, zone=Zone.LIBRARY)
    stack_library(engine, "p1", first)
    step(engine, "end")
    assert first.zone == Zone.EXILE and first.instance_id in engine.state.temp_play_permissions
    stack_library(engine, "p1", second)
    step(engine, "end")
    assert second.zone == Zone.EXILE and second.instance_id in engine.state.temp_play_permissions
    assert first.instance_id not in engine.state.temp_play_permissions


def test_furious_rise_needs_a_power_four_creature():
    engine = game()
    card(engine, "Furious Rise")
    filler(engine, "Small", power=3, toughness=3)
    top = filler(engine, "Top", type_line="Sorcery", mv=2, zone=Zone.LIBRARY)
    stack_library(engine, "p1", top)
    step(engine, "end")
    assert top.zone == Zone.LIBRARY


def test_inspiring_statuary_gives_nonartifact_spells_improvise():
    engine = game()
    card(engine, "Inspiring Statuary")
    spell = filler(engine, "Costly Elf", mv=2, power=2, toughness=2, zone=Zone.HAND)
    artifact_spell = filler(engine, "Costly Rock", type_line="Artifact", mv=2, zone=Zone.HAND)
    rocks = [filler(engine, f"Rock {i}", type_line="Artifact") for i in range(2)]
    assert engine._help_pay_keyword(spell) == "improvise"
    assert engine._help_pay_keyword(artifact_spell) is None
    me = engine.state.player_by_id("p1")
    main_phase(engine)
    engine.cast_spell(me, spell, help_pay=True)
    engine.resolve_until_stable()
    assert spell.zone == Zone.BATTLEFIELD and sum(1 for r in rocks if r.tapped) >= 1  # the artifacts paid its {2}


def test_professor_hojo_discounts_the_first_creature_targeting_ability_and_draws():
    engine = game()
    hojo = card(engine, "Professor Hojo")
    helm = card(engine, "Champion's Helm")  # equip {1}: targets a creature you control
    runner = filler(engine, "Runner", power=2, toughness=2)
    me = engine.state.player_by_id("p1")
    assert not me.mana_pool.total()
    hand = len(me.hand)
    activate(engine, helm, 0, targets=[runner])  # {1} - 2 = free
    assert helm.attached_to == runner.instance_id
    assert len(me.hand) == hand + 1  # a creature you control became the target of an ability
    me.mana_pool.add_many({"C": 1})
    other = filler(engine, "Other", power=1, toughness=1)
    activate(engine, helm, 0, targets=[other])  # the second one pays full price
    assert helm.attached_to == other.instance_id and me.mana_pool.total() == 0
    assert len(me.hand) == hand + 1  # only once each turn


def _chapter(engine, saga, chapter):
    engine.state.fire_event(GameEvent(EventType.SAGA_CHAPTER, instance_id=saga.instance_id, chapter=chapter,
                                      controller_id=saga.controller_id))
    engine.resolve_until_stable()


def test_yuffie_steals_a_noncreature_artifact_and_attaches_an_equipment():
    engine = game()
    rock = filler(engine, "Their Rock", type_line="Artifact", player="p2")
    helm = card(engine, "Champion's Helm")
    yuffie = put_on_battlefield(engine, "Yuffie, Materia Hunter")
    answer(engine, pick_label("Their Rock"))
    answer(engine, pick_label("Champion's Helm"))
    assert rock.controller_id == "p1" and helm.attached_to == yuffie.instance_id


def test_cait_sith_exiles_the_top_card_and_pumps_for_its_mana_value():
    engine = game()
    cait = card(engine, "Cait Sith, Fortune Teller")
    top = filler(engine, "Top Spell", type_line="Sorcery", mv=3, zone=Zone.LIBRARY)
    stack_library(engine, "p1", top)
    step(engine, "begin_combat")
    engine.resolve_pending_choice(pick_label("Cait")(engine.state.pending_choice))  # the pump's target
    engine.resolve_pending_choice("decline")  # scry: keep the rest on top
    assert top.zone == Zone.EXILE
    assert cait.power == 3 + 3


def test_soldier_military_program_makes_a_soldier_or_both_with_a_commander():
    engine = game()
    card(engine, "SOLDIER Military Program")
    step(engine, "begin_combat")
    answer(engine, pick_label("Soldat", "Soldier"))
    assert len(named(engine, "Soldier")) == 1


def test_sephiroth_sets_modified_creatures_to_7_5_when_attacking():
    engine = game()
    sephiroth = card(engine, "Sephiroth, Fallen Hero")
    marked = filler(engine, "Marked", power=1, toughness=1)
    marked.add_counters("+1/+1", 1)
    plain = filler(engine, "Plain", power=1, toughness=1)
    attack(engine, [sephiroth])
    answer(engine, pick_label("Plain"))  # the cell counter's target
    engine.recompute_continuous_effects()
    # base 7/5 (layer 7b), then the counters (7c)
    assert (marked.power, marked.toughness) == (8, 6)
    assert plain.counters.get("cell") == 1 and (plain.power, plain.toughness) == (7, 5)  # modified by the cell counter


def test_sephiroth_returns_from_the_graveyard_by_sacrificing_a_modified_creature():
    engine = game()
    sephiroth = card(engine, "Sephiroth, Fallen Hero")
    engine.rules.put_into_graveyard(sephiroth)
    engine.resolve_until_stable()
    marked = filler(engine, "Marked", power=1, toughness=1)
    marked.add_counters("+1/+1", 1)
    engine.state.player_by_id("p1").mana_pool.add_many({"C": 3})
    activate(engine, sephiroth, 0)
    assert sephiroth.zone == Zone.BATTLEFIELD and sephiroth.tapped and marked.zone == Zone.GRAVEYARD


def test_summon_kujata_chapters():
    engine = game()
    victim = filler(engine, "Victim", power=1, toughness=3, player="p2")
    other = filler(engine, "Other", power=1, toughness=3, player="p2")
    kujata = card(engine, "Summon: Kujata")  # entering fires chapter I
    engine.resolve_until_stable()
    answer(engine, pick_label("Victim", "Other"))
    answer(engine, pick_label("Victim", "Other"))
    assert victim.zone == Zone.GRAVEYARD or other.zone == Zone.GRAVEYARD
    me = engine.state.player_by_id("p1")
    expensive = filler(engine, "Expensive Card", type_line="Sorcery", mv=4, zone=Zone.HAND)
    _chapter(engine, kujata, 3)
    answer(engine, pick_label("Expensive Card"))
    assert engine.state.player_by_id("p2").life == 16

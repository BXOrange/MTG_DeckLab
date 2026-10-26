"""Tests for the rules engine + game engine.

Reference: docs/requirements/02_MVP_USECASES_REVISED.md R2.*/R4.*,
docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md, mtg_analyzer/game/.
"""

import pytest
from mtg_analyzer.game import combat

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game.binding.core import bind_from_catalogue


from engine_test_helpers import land, creature, make_engine, obj_on_battlefield, _to_declare_attackers, _attack_then_blockers_step, _goblin_guide_card


def test_recognizes_keywords_from_scryfall_list():
    card = creature(keywords=["Flying", "First strike", "Trample"])
    assert combat.keywords_of(card) == {"flying", "first_strike", "trample"}


def test_recognizes_keywords_from_oracle_text_clause():
    card = creature(oracle_text="Vigilance, lifelink\nDeathtouch")
    assert {"vigilance", "lifelink", "deathtouch"} <= combat.keywords_of(card)


def test_granting_a_keyword_is_not_a_false_positive():
    # "gains flying" is an *effect*, not the card having flying itself.
    card = creature(oracle_text="Target creature gains flying until end of turn.")
    assert "flying" not in combat.keywords_of(card)


def test_recognizes_protection_qualities():
    card = creature(oracle_text="Protection from red\nProtection from creatures")
    assert combat.protections_of(card) == {"R", "creatures"}
    assert "protection" in combat.keywords_of(card)


def test_display_keywords_expands_protection():
    card = creature(keywords=["Flying"], oracle_text="Protection from black")
    labels = combat.display_keywords(card)
    assert "Flying" in labels
    assert "Protection: B" in labels


def test_station_bracket_keyword_does_not_leak_unconditionally():
    # RULE 721.2a: "8+ | Flying, deathtouch" only grants those keywords at
    # 8+ charge counters (via the layer-6 grant `catalogue.station` feeds
    # `continuous.recompute`) — `keywords_of` must not also treat the
    # bracket line as unconditional text, the same leak `is_leveler`
    # already guards against for "LEVEL 7+" blocks. Regression test for a
    # real bug found live on Entropic Battlecruiser: "deathtouch" (comma-
    # anchored right after "8+ | ") matched the oracle-text fallback
    # unconditionally before `station_base_text` existed.
    card = creature(
        type_line="Artifact — Spacecraft",
        keywords=["Station"],
        oracle_text=(
            "Station (Tap another creature you control: Put charge counters "
            "equal to its power on this Spacecraft. Station only as a "
            "sorcery. It's an artifact creature at 8+.)\n"
            "1+ | Whenever an opponent discards a card, they lose 3 life.\n"
            "8+ | Flying, deathtouch\n"
            "Whenever this Spacecraft attacks, each opponent discards a card."
        ),
    )
    assert combat.keywords_of(card) == frozenset()


def test_station_unconditional_line_after_brackets_still_recognized():
    # RULE 721.4 allows an ordinary (bracket-less) line *after* the tier
    # brackets too — unlike Leveler's strict preamble-only shape. A real
    # unconditional keyword printed there must still be found, so the fix
    # above must filter bracket lines rather than truncate at the first one.
    card = creature(
        type_line="Artifact — Spacecraft",
        keywords=["Station"],
        oracle_text=(
            "Station (Tap another creature you control: Put charge counters "
            "equal to its power on this Spacecraft. Station only as a "
            "sorcery.)\n"
            "1+ | Flying\n"
            "Vigilance"
        ),
    )
    assert combat.keywords_of(card) == {"vigilance"}


def test_recognizes_multiple_protections_joined_by_and_from():
    # Official templating for a multi-quality protection repeats "from" per
    # quality (the Sword-of-X-and-Y equipment cycle: "Protection from red
    # and from blue"), rather than a bare "and".
    card = creature(oracle_text="Protection from red and from blue")
    assert combat.protections_of(card) == {"R", "U"}


def test_recognizes_protection_from_card_type():
    card = creature(oracle_text="Protection from artifacts")
    assert combat.protections_of(card) == {"artifacts"}


def test_protection_from_card_type_stops_damage_from_that_type():
    eng = make_engine([land()], [land()], hand=0)
    target = obj_on_battlefield(
        eng.state, eng, creature(name="Ward", oracle_text="Protection from artifacts")
    )
    artifact_source = obj_on_battlefield(
        eng.state,
        eng,
        Card(id="Blaster", name="Blaster", type_line="Artifact Creature — Golem",
             is_creature=True, power=3, toughness=3),
        controller="p2",
    )
    eng.rules.deal_damage(target, 3, source=artifact_source)
    assert target.damage_marked == 0


def test_protection_from_creature_type_stops_damage_from_that_type():
    eng = make_engine([land()], [land()], hand=0)
    target = obj_on_battlefield(
        eng.state, eng, creature(name="Ward", oracle_text="Protection from Dragons")
    )
    dragon = obj_on_battlefield(
        eng.state,
        eng,
        creature(name="Dragon", type_line="Creature — Dragon", power=5, toughness=5),
        controller="p2",
    )
    eng.rules.deal_damage(target, 5, source=dragon)
    assert target.damage_marked == 0


def test_noncombat_damage_prevented_by_protection():
    # RULE 702.16c: protection prevents *all* damage from a source of the
    # stated quality, not just combat damage — a burn spell fizzles too.
    eng = make_engine([land()], [land()], hand=0)
    target = obj_on_battlefield(
        eng.state, eng, creature(name="Ward", oracle_text="Protection from red")
    )
    red_source = obj_on_battlefield(
        eng.state,
        eng,
        Card(
            id="Bolt",
            name="Bolt",
            type_line="Instant",
            mana_cost_string="{R}",
            converted_mana_cost=1,
            is_instant=True,
            color_identity={"R"},
        ),
        controller="p2",
    )
    eng.rules.deal_damage(target, 5, source=red_source)
    assert target.damage_marked == 0


def test_equipment_target_options_exclude_protected_creature():
    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player

    legal_host = obj_on_battlefield(eng.state, eng, creature(name="Host", cost="{1}"))
    protected_host = obj_on_battlefield(
        eng.state, eng, creature(name="Ward", oracle_text="Protection from artifacts")
    )

    card = Card(
        id="Equipment",
        name="Equipment",
        type_line="Artifact — Equipment",
        mana_cost_string="{1}",
        converted_mana_cost=1,
    )
    card.keywords = ["Equip"]
    card.oracle_text = "Equip {2}"
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    eng.state.add_to_battlefield(source)
    bind_from_catalogue(source)

    requirements = eng._ability_target_requirements(p1, source.activated_abilities[0], source)
    option_ids = {opt["instance_id"] for opt in requirements[0]["options"]}

    assert legal_host.instance_id in option_ids
    assert protected_host.instance_id not in option_ids


def test_vigilance_attacker_does_not_tap():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    bear = obj_on_battlefield(eng.state, eng, creature(power=3, keywords=["Vigilance"]))
    eng.declare_attackers(eng.state.active_player, [bear])
    assert bear.attacking and not bear.tapped


def test_haste_creature_can_attack_when_summoning_sick():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    hasty = obj_on_battlefield(eng.state, eng, creature(power=2, keywords=["Haste"]))
    hasty.summoning_sick = True
    eng.declare_attackers(eng.state.active_player, [hasty])  # no raise
    assert hasty.attacking


def test_defender_cannot_attack():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    wall = obj_on_battlefield(eng.state, eng, creature(power=0, toughness=4, keywords=["Defender"]))
    with pytest.raises(ValueError):
        eng.declare_attackers(eng.state.active_player, [wall])


def test_flyer_cannot_be_blocked_by_ground_creature():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    flyer = obj_on_battlefield(eng.state, eng, creature(power=2, keywords=["Flying"]))
    ground = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    p2 = _attack_then_blockers_step(eng, flyer)
    assert not eng.can_block(p2, ground, flyer)
    with pytest.raises(ValueError):
        eng.declare_blockers(p2, [{"blocker": ground, "attacker": flyer}])


def test_flyer_can_be_blocked_by_flyer_or_reach():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    flyer = obj_on_battlefield(eng.state, eng, creature(power=2, keywords=["Flying"]))
    other_flyer = obj_on_battlefield(eng.state, eng, creature(keywords=["Flying"]), controller="p2")
    spider = obj_on_battlefield(eng.state, eng, creature(keywords=["Reach"]), controller="p2")
    p2 = _attack_then_blockers_step(eng, flyer)
    assert eng.can_block(p2, other_flyer, flyer)
    assert eng.can_block(p2, spider, flyer)


def test_protection_from_color_stops_that_color_blocking():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = obj_on_battlefield(
        eng.state, eng, creature(power=2, oracle_text="Protection from red")
    )
    red_blocker = obj_on_battlefield(
        eng.state, eng, creature(color_identity={"R"}), controller="p2"
    )
    white_blocker = obj_on_battlefield(
        eng.state, eng, creature(color_identity={"W"}), controller="p2"
    )
    p2 = _attack_then_blockers_step(eng, attacker)
    assert not eng.can_block(p2, red_blocker, attacker)
    assert eng.can_block(p2, white_blocker, attacker)


def test_islandwalk_is_unblockable_while_defender_controls_an_island():
    # RULE 702.14b: an islandwalker can't be blocked while the defending
    # player controls an Island.
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    walker = obj_on_battlefield(eng.state, eng, creature(power=2, keywords=["Islandwalk"]))
    blocker = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    obj_on_battlefield(eng.state, eng, land(produces="Island"), controller="p2")
    p2 = _attack_then_blockers_step(eng, walker)
    assert not eng.can_block(p2, blocker, walker)
    with pytest.raises(ValueError):
        eng.declare_blockers(p2, [{"blocker": blocker, "attacker": walker}])


def test_islandwalk_is_blockable_when_defender_has_no_island():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    walker = obj_on_battlefield(eng.state, eng, creature(power=2, keywords=["Islandwalk"]))
    blocker = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    obj_on_battlefield(eng.state, eng, land(produces="Forest"), controller="p2")
    p2 = _attack_then_blockers_step(eng, walker)
    assert eng.can_block(p2, blocker, walker)


def test_menace_requires_two_blockers():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    menacer = obj_on_battlefield(eng.state, eng, creature(power=3, keywords=["Menace"]))
    b1 = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    b2 = obj_on_battlefield(eng.state, eng, creature(), controller="p2")
    eng.declare_attackers(eng.state.active_player, [menacer])
    eng.state.current_step = "declare_blockers"
    p2 = eng.state.player_by_id("p2")
    with pytest.raises(ValueError):  # a single blocker is illegal
        eng.declare_blockers(p2, [{"blocker": b1, "attacker": menacer}])
    assert menacer.blocked_by == []  # nothing mutated on the failed attempt
    eng.declare_blockers(
        p2,
        [{"blocker": b1, "attacker": menacer}, {"blocker": b2, "attacker": menacer}],
    )
    assert set(menacer.blocked_by) == {b1.instance_id, b2.instance_id}


def test_first_strike_kills_blocker_before_it_strikes_back():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = obj_on_battlefield(
        eng.state, eng, creature(power=2, toughness=2, keywords=["First strike"])
    )
    blocker = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    p2 = _attack_then_blockers_step(eng, attacker)
    eng.declare_blockers(p2, [{"blocker": blocker, "attacker": attacker}])
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    # First strike deals 2 first → the 2/2 blocker dies before it can hit back.
    assert blocker not in eng.state.battlefield
    assert attacker in eng.state.battlefield
    assert attacker.damage_marked == 0


def test_double_strike_deals_damage_twice():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = obj_on_battlefield(
        eng.state, eng, creature(power=2, toughness=2, keywords=["Double strike"])
    )
    eng.declare_attackers(eng.state.active_player, [attacker])
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    # An unblocked 2-power double striker deals 2 + 2 = 4 to the opponent.
    assert eng.state.player_by_id("p2").life == 16


def test_deathtouch_makes_any_damage_lethal():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    deathtoucher = obj_on_battlefield(
        eng.state, eng, creature(power=1, toughness=1, keywords=["Deathtouch"])
    )
    big = obj_on_battlefield(eng.state, eng, creature(power=1, toughness=5), controller="p2")
    p2 = _attack_then_blockers_step(eng, deathtoucher)
    eng.declare_blockers(p2, [{"blocker": big, "attacker": deathtoucher}])
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    assert big not in eng.state.battlefield


def test_trample_spills_excess_onto_defender():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    trampler = obj_on_battlefield(
        eng.state, eng, creature(power=5, toughness=5, keywords=["Trample"])
    )
    chump = obj_on_battlefield(eng.state, eng, creature(power=0, toughness=2), controller="p2")
    p2 = _attack_then_blockers_step(eng, trampler)
    eng.declare_blockers(p2, [{"blocker": chump, "attacker": trampler}])
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    # 2 lethal to the 0/2 chump, 3 tramples over to the player.
    assert chump not in eng.state.battlefield
    assert eng.state.player_by_id("p2").life == 17


def test_deathtouch_trample_assigns_one_then_tramples():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = obj_on_battlefield(
        eng.state, eng, creature(power=5, toughness=5, keywords=["Trample", "Deathtouch"])
    )
    wall = obj_on_battlefield(eng.state, eng, creature(power=0, toughness=4), controller="p2")
    p2 = _attack_then_blockers_step(eng, attacker)
    eng.declare_blockers(p2, [{"blocker": wall, "attacker": attacker}])
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    # Deathtouch → 1 damage is lethal, so only 1 need go to the wall; 4 tramples.
    assert wall not in eng.state.battlefield
    assert eng.state.player_by_id("p2").life == 16


def test_lifelink_gains_life_on_combat_damage():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = obj_on_battlefield(eng.state, eng, creature(power=3, keywords=["Lifelink"]))
    p1 = eng.state.active_player
    start = p1.life
    eng.declare_attackers(p1, [attacker])
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    assert eng.state.player_by_id("p2").life == 17
    assert p1.life == start + 3


def test_infect_combat_damage_to_player_is_poison_not_life_loss():
    # RULE 702.90c: an infect source's combat damage to a player becomes
    # poison counters, with no life loss at all.
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = obj_on_battlefield(eng.state, eng, creature(power=3, keywords=["Infect"]))
    p1 = eng.state.active_player
    eng.declare_attackers(p1, [attacker])
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    p2 = eng.state.player_by_id("p2")
    assert p2.poison == 3
    assert p2.life == 20


def test_infect_combat_damage_to_creature_is_minus_counters_not_marked():
    # RULE 702.90b: an infect source's damage to a creature is -1/-1
    # counters, not marked damage (so it isn't cleared at cleanup — it's a
    # permanent P/T reduction, unlike ordinary combat damage).
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = obj_on_battlefield(eng.state, eng, creature(power=2, keywords=["Infect"]))
    wall = obj_on_battlefield(eng.state, eng, creature(power=0, toughness=5), controller="p2")
    p2 = _attack_then_blockers_step(eng, attacker)
    eng.declare_blockers(p2, [{"blocker": wall, "attacker": attacker}])
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    assert wall.damage_marked == 0
    assert wall.counters.get("-1/-1") == 2


def test_wither_damage_to_creature_is_minus_counters_but_player_still_loses_life():
    # RULE 702.91a: wither is the creature-only half of infect's damage
    # substitution — a wither source's damage to a *player* is ordinary
    # life loss.
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = obj_on_battlefield(eng.state, eng, creature(power=2, keywords=["Wither"]))
    wall = obj_on_battlefield(eng.state, eng, creature(power=0, toughness=5), controller="p2")
    p2 = _attack_then_blockers_step(eng, attacker)
    eng.declare_blockers(p2, [{"blocker": wall, "attacker": attacker}])
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    assert wall.damage_marked == 0
    assert wall.counters.get("-1/-1") == 2

    eng2 = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng2)
    attacker2 = obj_on_battlefield(eng2.state, eng2, creature(power=3, keywords=["Wither"]))
    p1 = eng2.state.active_player
    eng2.declare_attackers(p1, [attacker2])
    eng2.state.current_step = "combat_damage"
    eng2._step_combat_damage()
    p2b = eng2.state.player_by_id("p2")
    assert p2b.poison == 0
    assert p2b.life == 17


def test_goblin_guide_puts_a_revealed_land_into_the_defenders_hand():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    guide = obj_on_battlefield(eng.state, eng, _goblin_guide_card())
    bind_from_catalogue(guide)
    p2 = eng.state.player_by_id("p2")
    top_land = land("Island")
    top_land_obj = GameObject(top_land, owner_id="p2", zone=Zone.LIBRARY)
    p2.library.append(top_land_obj)  # top of deck is the list end
    hand_before = len(p2.hand)

    eng.declare_attackers(eng.state.active_player, [guide])
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.resolve_until_stable()

    assert top_land_obj in p2.hand
    assert top_land_obj not in p2.library
    assert len(p2.hand) == hand_before + 1


def test_goblin_guide_leaves_a_revealed_nonland_card_on_top():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    guide = obj_on_battlefield(eng.state, eng, _goblin_guide_card())
    bind_from_catalogue(guide)
    p2 = eng.state.player_by_id("p2")
    top_spell = creature(name="Not A Land")
    top_spell_obj = GameObject(top_spell, owner_id="p2", zone=Zone.LIBRARY)
    p2.library.append(top_spell_obj)
    library_count_before = len(p2.library)

    eng.declare_attackers(eng.state.active_player, [guide])
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()

    assert top_spell_obj in p2.library
    assert top_spell_obj not in p2.hand
    assert len(p2.library) == library_count_before


def test_protection_prevents_combat_damage():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    attacker = obj_on_battlefield(
        eng.state, eng, creature(power=3, toughness=3, oracle_text="Protection from red")
    )
    # A red blocker: it can't block (protection), so force the reverse — a red
    # attacker blocked by our protected creature to check damage prevention.
    eng2 = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng2)
    red_attacker = obj_on_battlefield(
        eng2.state, eng2, creature(power=3, toughness=3, color_identity={"R"})
    )
    protector = obj_on_battlefield(
        eng2.state,
        eng2,
        creature(power=1, toughness=3, oracle_text="Protection from red"),
        controller="p2",
    )
    eng2.declare_attackers(eng2.state.active_player, [red_attacker])
    eng2.state.current_step = "declare_blockers"
    p2 = eng2.state.player_by_id("p2")
    eng2.declare_blockers(p2, [{"blocker": protector, "attacker": red_attacker}])
    eng2.state.current_step = "combat_damage"
    eng2._step_combat_damage()
    # The red attacker's damage to the protected blocker is prevented; the
    # blocker still deals its 1 back.
    assert protector in eng2.state.battlefield
    assert protector.damage_marked == 0
    assert red_attacker.damage_marked == 1


def test_indestructible_survives_lethal_and_deathtouch():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    tough = obj_on_battlefield(
        eng.state, eng, creature(power=1, toughness=1, keywords=["Indestructible"])
    )
    killer = obj_on_battlefield(
        eng.state, eng, creature(power=6, toughness=1, keywords=["Deathtouch"]), controller="p2"
    )
    p2 = _attack_then_blockers_step(eng, tough)
    eng.declare_blockers(p2, [{"blocker": killer, "attacker": tough}])
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    # 6 damage from a deathtouch source, but indestructible → it survives.
    assert tough in eng.state.battlefield


def test_deathtouch_flag_cleared_at_end_of_combat():
    eng = make_engine([land()], [land()], hand=0)
    _to_declare_attackers(eng)
    survivor = obj_on_battlefield(
        eng.state, eng, creature(power=1, toughness=1, keywords=["Indestructible"])
    )
    dt = obj_on_battlefield(
        eng.state, eng, creature(power=1, toughness=1, keywords=["Deathtouch"]), controller="p2"
    )
    p2 = _attack_then_blockers_step(eng, survivor)
    eng.declare_blockers(p2, [{"blocker": dt, "attacker": survivor}])
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    assert survivor.dealt_deathtouch_damage is True  # marked during combat
    eng._step_end_combat()
    eng._finish_end_combat()  # RULE 511.3: removal happens as the step ends (BUG-30)
    assert survivor.dealt_deathtouch_damage is False

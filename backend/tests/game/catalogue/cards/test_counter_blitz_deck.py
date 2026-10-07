"""Gameplay regressions for the Counter Blitz (Final Fantasy Commander) deck batch."""
from mtg_analyzer.game import continuous
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import (
    RICH, activate, answer, attack, card, cast, enter, filler, game, named, pick_label, put_on_battlefield, stack_library, step,
)


def _rigging_with_hidden_spell(power):
    engine = game()
    spell = filler(engine, "Hidden Spell", type_line="Sorcery", mv=3, zone=Zone.LIBRARY)
    stack_library(engine, "p1", spell)
    put_on_battlefield(engine, "Fight Rigging")
    answer(engine)  # the hideaway pick
    big = filler(engine, "Big", power=power, toughness=6)
    step(engine, "begin_combat")
    engine.resolve_pending_choice(pick_label("Big")(engine.state.pending_choice))  # the counter's target only
    return engine, spell, big


def test_fight_rigging_plays_the_hidden_card_with_a_power_seven_creature():
    engine, spell, big = _rigging_with_hidden_spell(6)
    assert big.counters.get("+1/+1") == 1 and big.power == 7
    assert engine.state.pending_choice["kind"] == "play_during_resolution"
    engine.cast_spell(engine.state.player_by_id("p1"), spell)  # free: the offer lifts the cost
    engine.resolve_until_stable()
    assert spell.zone != Zone.EXILE


def test_fight_rigging_keeps_the_card_hidden_without_a_power_seven_creature():
    engine, spell, big = _rigging_with_hidden_spell(5)
    assert big.power == 6 and spell.zone == Zone.EXILE
    assert engine.state.pending_choice is None


def test_lord_jyscal_investigates_at_end_step_after_a_counter():
    engine = game()
    card(engine, "Lord Jyscal Guado")
    bear = filler(engine, "Bear", power=1, toughness=1)
    step(engine, "end")
    assert not named(engine, "Clue")
    engine.rules.add_counters(bear, 1, "+1/+1", source=bear)
    step(engine, "end")
    assert named(engine, "Clue")


def test_generous_patron_draws_when_you_put_counters_on_an_opposing_creature():
    engine = game()
    card(engine, "Generous Patron")
    theirs = filler(engine, "Theirs", power=2, toughness=2, player="p2")
    mine = filler(engine, "Mine", power=2, toughness=2)
    me = engine.state.player_by_id("p1")
    hand = len(me.hand)
    engine.rules.add_counters(mine, 1, "+1/+1", source=mine)
    engine.resolve_until_stable()
    assert len(me.hand) == hand
    engine.rules.add_counters(theirs, 1, "+1/+1", source=mine)
    engine.resolve_until_stable()
    assert len(me.hand) == hand + 1


def test_blitzball_stadium_makes_a_creature_unblockable_and_draws_per_counter_kind():
    engine = game()
    stadium = card(engine, "Blitzball Stadium")
    runner = filler(engine, "Runner", power=2, toughness=2)
    runner.add_counters("+1/+1", 1)
    runner.add_counters("shield", 1)
    engine.state.player_by_id("p1").mana_pool.add_many({"C": 3})
    activate(engine, stadium, 0, targets=[runner])
    me = engine.state.player_by_id("p1")
    hand = len(me.hand)
    engine.state.fire_event(GameEvent(EventType.DAMAGE, source_id=runner.instance_id, source_controller_id="p1",
                                      target_id="p2", is_player=True, combat=True, amount=2))
    engine.resolve_until_stable()
    assert len(me.hand) == hand + 2


def test_chocobo_knights_grants_double_strike_to_creatures_with_counters_when_you_attack():
    engine = game()
    card(engine, "Chocobo Knights")
    marked = filler(engine, "Marked", power=2, toughness=2)
    plain = filler(engine, "Plain", power=2, toughness=2)
    marked.add_counters("+1/+1", 1)
    attack(engine, [plain])
    from mtg_analyzer.game import combat
    assert combat.has(marked, "double strike") and not combat.has(plain, "double strike")


def test_gatta_and_luzzu_turns_prevented_damage_into_counters():
    engine = game()
    ally = filler(engine, "Ally", power=2, toughness=2)
    put_on_battlefield(engine, "Gatta and Luzzu")
    answer(engine, pick_label("Ally"))
    engine.rules.deal_damage(ally, 3, source=filler(engine, "Their Bear", power=3, toughness=3, player="p2"))
    assert ally.damage_marked == 0 and ally.counters.get("+1/+1") == 3


def test_rampant_rejuvenator_fetches_basic_lands_equal_to_its_power_when_it_dies():
    engine = game()
    for i in range(3):
        filler(engine, f"Basic {i}", type_line="Basic Land — Forest", zone=Zone.LIBRARY)
    rejuvenator = card(engine, "Rampant Rejuvenator", zone=Zone.HAND)
    cast(engine, rejuvenator)  # cast, so its entry counters are applied
    assert rejuvenator.counters.get("+1/+1") == 2
    engine.rules.put_into_graveyard(rejuvenator)
    engine.resolve_until_stable()
    answer(engine)
    lands = [o for o in engine.state.battlefield if o.is_land and o.controller_id == "p1"]
    assert len(lands) == 2  # X = the dying creature's power (two +1/+1 counters on a 0/0)


def test_auron_counters_himself_and_exiles_a_weaker_defending_creature():
    engine = game()
    auron = card(engine, "Auron, Venerated Guardian")
    weak = filler(engine, "Weak", power=2, toughness=2, player="p2")
    strong = filler(engine, "Strong", power=3, toughness=3, player="p2")
    attack(engine, [auron])
    answer(engine, pick_label("Weak"))
    assert auron.counters.get("+1/+1") == 1 and auron.power == 3
    assert weak.zone == Zone.EXILE and strong.zone == Zone.BATTLEFIELD
    engine.rules.put_into_graveyard(auron)
    engine.resolve_until_stable()
    assert weak.zone == Zone.BATTLEFIELD


def test_endless_detour_lets_the_owner_of_a_graveyard_card_choose_top_or_bottom():
    engine = game()
    detour = card(engine, "Endless Detour", zone=Zone.HAND)
    corpse = filler(engine, "Corpse", power=2, toughness=2, player="p2", zone=Zone.GRAVEYARD)
    cast(engine, detour, targets=[corpse])
    choice = engine.state.pending_choice
    assert choice["kind"] == "library_position" and choice["player_id"] == "p2"
    engine.resolve_pending_choice("top")
    assert corpse.zone == Zone.LIBRARY and engine.state.player_by_id("p2").library[-1] is corpse


def test_endless_detour_pulls_a_spell_off_the_stack_into_its_owners_library():
    engine = game()
    detour = card(engine, "Endless Detour", zone=Zone.HAND)
    spell = filler(engine, "Their Instant", type_line="Instant", mv=2, player="p2", zone=Zone.HAND)
    p2 = engine.state.player_by_id("p2")
    main_phase_pool = {"C": 2}
    from tests.support.deck_batch import main_phase
    main_phase(engine)
    p2.mana_pool.add_many(main_phase_pool)
    engine.cast_spell(p2, spell)
    cast(engine, detour, targets=[engine.state.stack[0]])
    engine.resolve_pending_choice("bottom")
    assert spell.zone == Zone.LIBRARY and engine.state.player_by_id("p2").library[0] is spell


def test_collective_effort_escalate_taps_one_creature_per_extra_mode():
    engine = game()
    spell = card(engine, "Collective Effort", zone=Zone.HAND)
    big = filler(engine, "Their Big", power=5, toughness=5, player="p2")
    their_wolf = filler(engine, "Their Wolf", power=2, toughness=2, player="p2")
    mine = [filler(engine, f"Mine {i}", power=1 + i, toughness=3) for i in range(3)]
    cast(engine, spell, targets=[big, engine.state.player_by_id("p1")], mode=[0, 2])
    assert big.zone == Zone.GRAVEYARD  # mode 1: destroy power >= 4
    assert sum(1 for o in mine if o.tapped) == 1  # one extra mode: one creature tapped (the weakest)
    assert mine[0].tapped
    assert all(o.counters.get("+1/+1") == 1 for o in mine)  # mode 3 on "target player" = you
    assert their_wolf.counters.get("+1/+1") is None


def test_collective_effort_cannot_pay_escalate_without_untapped_creatures():
    import pytest

    engine = game()
    spell = card(engine, "Collective Effort", zone=Zone.HAND)
    big = filler(engine, "Their Big", power=5, toughness=5, player="p2")
    with pytest.raises(ValueError):
        cast(engine, spell, targets=[big, engine.state.player_by_id("p1")], mode=[0, 2])


def test_lulu_stuns_an_attacker_when_an_opponent_attacks_you():
    engine = game()
    card(engine, "Lulu, Stern Guardian")
    engine.state.active_player_index = 1
    bear = filler(engine, "Bear", power=2, toughness=2, player="p2")
    attack(engine, [bear])
    answer(engine)
    assert bear.counters.get("stun") == 1


def test_wakka_pumps_the_team_at_end_step_only_if_he_got_a_counter():
    engine = game()
    wakka = card(engine, "Wakka, Devoted Guardian")
    ally = filler(engine, "Ally", power=1, toughness=1)
    step(engine, "end")
    assert not ally.counters.get("+1/+1")
    engine.rules.add_counters(wakka, 1, "+1/+1", source=wakka)
    step(engine, "end")
    assert ally.counters.get("+1/+1") == 1 and wakka.counters.get("+1/+1") == 1


def test_wakka_destroys_an_artifact_and_grows_on_combat_damage():
    engine = game()
    wakka = card(engine, "Wakka, Devoted Guardian")
    rock = filler(engine, "Rock", type_line="Artifact", player="p2")
    engine.state.fire_event(GameEvent(EventType.DAMAGE, source_id=wakka.instance_id, source_controller_id="p1",
                                      target_id="p2", is_player=True, combat=True, amount=4))
    engine.resolve_until_stable()
    answer(engine, pick_label("Rock"))
    assert rock.zone == Zone.GRAVEYARD and wakka.counters.get("+1/+1") == 1


def test_tidus_moves_a_counter_at_beginning_of_combat():
    engine = game()
    card(engine, "Tidus, Yuna's Guardian")
    giver = filler(engine, "Giver", power=2, toughness=2)
    taker = filler(engine, "Taker", power=2, toughness=2)
    giver.add_counters("+1/+1", 1)
    step(engine, "begin_combat")
    engine.resolve_pending_choice(pick_label("Giver")(engine.state.pending_choice))  # the source of the counter
    engine.resolve_pending_choice(pick_label("Taker")(engine.state.pending_choice))  # the second target
    assert taker.counters.get("+1/+1") == 1 and not giver.counters.get("+1/+1")


def test_rikku_makes_a_creature_unblockable_when_you_put_a_counter_on_it():
    engine = game()
    card(engine, "Rikku, Resourceful Guardian")
    runner = filler(engine, "Runner", power=2, toughness=2)
    blocker = filler(engine, "Blocker", power=2, toughness=2, player="p2")
    engine.rules.add_counters(runner, 1, "+1/+1", source=runner)
    engine.resolve_until_stable()
    answer(engine)
    assert runner.temp_combat_restrictions


def test_rikku_steals_a_counter_from_an_opposing_creature():
    engine = game()
    rikku = card(engine, "Rikku, Resourceful Guardian")
    theirs = filler(engine, "Theirs", power=2, toughness=2, player="p2")
    mine = filler(engine, "Mine", power=1, toughness=1)
    theirs.add_counters("+1/+1", 1)
    engine.state.player_by_id("p1").mana_pool.add_many({"C": 1})
    activate(engine, rikku, 0, targets=[theirs, mine])
    assert mine.counters.get("+1/+1") == 1 and not theirs.counters.get("+1/+1")


def test_together_forever_returns_the_marked_creature_to_hand_when_it_dies():
    engine = game()
    forever = card(engine, "Together Forever")
    marked = filler(engine, "Marked", power=2, toughness=2)
    marked.add_counters("+1/+1", 1)
    engine.state.player_by_id("p1").mana_pool.add_many({"C": 1})
    activate(engine, forever, 0, targets=[marked])
    engine.rules.put_into_graveyard(marked)
    engine.resolve_until_stable()
    assert marked.zone == Zone.HAND


def test_maester_seymour_puts_counters_equal_to_his_power_and_goes_monstrous():
    engine = game()
    seymour = card(engine, "Maester Seymour")
    ally = filler(engine, "Ally", power=1, toughness=1)
    step(engine, "begin_combat")
    answer(engine, pick_label("Ally"))
    assert ally.counters.get("+1/+1") == 1  # Seymour's power (1)
    engine.state.player_by_id("p1").mana_pool.add_many({"G": 2, "C": 3})
    activate(engine, seymour, 0)
    assert seymour.counters.get("+1/+1") == 1  # X = counters among creatures you control = 1


def test_tromell_gives_other_nontoken_creatures_an_extra_counter_and_proliferates_per_entry():
    engine = game()
    tromell = card(engine, "Tromell, Seymour's Butler")
    bear = card(engine, "Grizzly Bears", zone=Zone.HAND)
    cast(engine, bear)
    assert bear.counters.get("+1/+1") == 1
    engine.state.player_by_id("p1").mana_pool.add_many({"C": 1})
    activate(engine, tromell, 0)
    assert bear.counters.get("+1/+1") == 2  # one nontoken creature entered this turn -> proliferate once


def test_scholar_of_new_horizons_fetches_a_plains_to_hand_or_battlefield():
    engine = game()
    plains = [filler(engine, f"Plains {i}", type_line="Basic Land — Plains", zone=Zone.LIBRARY) for i in range(2)]
    scholar = card(engine, "Scholar of New Horizons", zone=Zone.HAND)
    cast(engine, scholar)
    scholar.summoning_sick = False
    activate(engine, scholar, 0)
    answer(engine, pick_label("Plains"))
    assert any(p.zone == Zone.HAND for p in plains)
    filler(engine, "Their Land", type_line="Basic Land — Forest", player="p2")
    scholar.tapped = False
    scholar.counters["+1/+1"] = 1
    activate(engine, scholar, 0)
    answer(engine, pick_label("Plains"))
    assert any(p.zone == Zone.BATTLEFIELD and p.tapped for p in plains)


def test_forge_of_heroes_counters_a_commander_that_entered_this_turn():
    engine = game()
    forge = card(engine, "Forge of Heroes")
    commander = filler(engine, "Commander", power=3, toughness=3)
    commander.is_commander = True
    commander.turn_entered = engine.state.internal_turn.number
    activate(engine, forge, 0, targets=[commander])
    assert commander.counters.get("+1/+1") == 1


def test_kimahri_counters_himself_taps_a_creature_and_may_copy_it():
    engine = game()
    kimahri = card(engine, "Kimahri, Valiant Guardian")
    prey = card(engine, "Serra Angel", player="p2")
    step(engine, "begin_combat")
    answer(engine, pick_label("Serra Angel"))
    answer(engine, lambda c: next((str(o["id"]) for o in c.get("options", []) if o.get("id") in ("yes", "do")), None))
    assert prey.tapped and kimahri.card.name == "Kimahri, Valiant Guardian"
    assert kimahri.card.type_line.endswith("Angel") and kimahri.power == 5  # Serra Angel's 4/4 plus the counter Kimahri put on himself


def test_summoners_sending_exiles_a_creature_card_and_makes_a_spirit():
    engine = game()
    card(engine, "Summoner's Sending")
    big = filler(engine, "Big Dead", power=5, toughness=5, mv=5, player="p2", zone=Zone.GRAVEYARD)
    step(engine, "end")
    answer(engine, pick_label("Big Dead"))
    spirits = named(engine, "Spirit")
    assert big.zone == Zone.EXILE and len(spirits) == 1 and spirits[0].counters.get("+1/+1") == 1


def test_yunas_decision_modes():
    engine = game()
    spell = card(engine, "Yuna's Decision", zone=Zone.HAND)
    fodder = filler(engine, "Fodder", power=1, toughness=1)
    bear = filler(engine, "Hand Bear", power=2, toughness=2, zone=Zone.HAND)
    land = filler(engine, "Hand Land", type_line="Basic Land — Forest", zone=Zone.HAND)
    cast(engine, spell, mode=[0])
    answer(engine, lambda c: next((str(o["id"]) for o in c.get("options", []) if o.get("label") in ("Fodder", "Hand Bear", "Hand Land")), None))
    assert fodder.zone == Zone.GRAVEYARD
    assert bear.zone == Zone.BATTLEFIELD and land.zone == Zone.BATTLEFIELD


def test_yunas_decision_returns_permanent_cards_from_the_graveyard():
    engine = game()
    spell = card(engine, "Yuna's Decision", zone=Zone.HAND)
    one = filler(engine, "Gone One", type_line="Artifact", zone=Zone.GRAVEYARD)
    two = filler(engine, "Gone Two", power=1, toughness=1, zone=Zone.GRAVEYARD)
    cast(engine, spell, mode=[1], targets=[one, two])
    assert one.zone == Zone.HAND and two.zone == Zone.HAND


def _chapter(engine, saga, chapter):
    engine.state.fire_event(GameEvent(EventType.SAGA_CHAPTER, instance_id=saga.instance_id, chapter=chapter,
                                      controller_id=saga.controller_id))
    engine.resolve_until_stable()


def test_summon_ixion_exiles_until_it_leaves_then_pumps_and_gains_life():
    engine = game()
    ixion = card(engine, "Summon: Ixion", zone=Zone.HAND)
    prey = filler(engine, "Prey", power=3, toughness=3, player="p2")
    cast(engine, ixion)
    answer(engine, pick_label("Prey"))
    assert prey.zone == Zone.EXILE
    ally = filler(engine, "Ally", power=1, toughness=1)
    me = engine.state.player_by_id("p1")
    life = me.life
    _chapter(engine, ixion, 2)
    answer(engine, pick_label("Ally"))
    assert ally.counters.get("+1/+1") == 1 and me.life == life + 2
    engine.rules.put_into_graveyard(ixion)
    engine.resolve_until_stable()
    assert prey.zone == Zone.BATTLEFIELD


def _magus_sisters(mode):
    engine = game()
    ally = filler(engine, "Ally", power=1, toughness=1)
    them = filler(engine, "Them", power=1, toughness=1, player="p2")
    engine.rules.random_choice = lambda options: options[mode]  # pin "choose one at random"
    sisters = card(engine, "Summon: Magus Sisters")  # entering fires chapter I
    engine.resolve_until_stable()
    answer(engine, pick_label("Ally", "Them"))
    return engine, sisters, ally, them


def test_summon_magus_sisters_combine_powers():
    engine, sisters, ally, them = _magus_sisters(0)
    assert sum(o.counters.get("+1/+1", 0) for o in (ally, them, sisters)) == 3


def test_summon_magus_sisters_defense():
    engine, sisters, ally, them = _magus_sisters(1)
    assert sum(o.counters.get("shield", 0) for o in (ally, them, sisters)) == 1
    assert engine.state.player_by_id("p1").life == 23


def test_summon_magus_sisters_fight():
    engine, sisters, ally, them = _magus_sisters(2)
    assert them.zone != Zone.BATTLEFIELD  # the 5/5 Saga creature fights the 1/1


def test_summon_valefor_bounces_each_opponents_most_expensive_creature_then_stuns():
    engine = game()
    cheap = filler(engine, "Cheap", power=1, toughness=1, mv=1, player="p2")
    pricey = filler(engine, "Pricey", power=5, toughness=5, mv=6, player="p2")
    valefor = card(engine, "Summon: Valefor")  # entering fires chapter I
    engine.resolve_until_stable()
    assert pricey.zone == Zone.HAND and cheap.zone == Zone.BATTLEFIELD
    _chapter(engine, valefor, 2)
    answer(engine, pick_label("Cheap"))
    assert cheap.tapped and cheap.counters.get("stun") == 1


def test_summon_yojimbo_exiles_taxes_attacks_and_makes_treasures():
    engine = game()
    tapped = filler(engine, "Tapped Big", power=5, toughness=5, player="p2")
    tapped.tapped = True
    yojimbo = card(engine, "Summon: Yojimbo")  # entering fires chapter I
    engine.resolve_until_stable()
    answer(engine, pick_label("Tapped Big"))
    assert tapped.zone == Zone.EXILE
    _chapter(engine, yojimbo, 2)
    me = engine.state.player_by_id("p1")
    assert continuous.attack_tax_per_creature_for(engine.state, "p1", "player") == 2
    big = filler(engine, "Their Big", power=4, toughness=4, player="p2")
    _chapter(engine, yojimbo, 4)
    assert len(named(engine, "Treasure")) == 1


def test_sin_strips_counters_enters_with_twice_as_many_and_passes_them_on_when_it_dies():
    engine = game()
    ally = filler(engine, "Ally", power=1, toughness=1)
    ally.add_counters("+1/+1", 2)
    sin = card(engine, "Sin, Unending Cataclysm", zone=Zone.HAND)
    cast(engine, sin)
    answer(engine, pick_label("Ally"))
    assert not ally.counters.get("+1/+1") and sin.counters.get("+1/+1") == 4
    engine.rules.put_into_graveyard(sin)
    engine.resolve_until_stable()
    answer(engine, pick_label("Ally"))
    assert ally.counters.get("+1/+1") == 4
    assert sin.zone == Zone.LIBRARY


def test_valefor_lets_each_opponent_choose_a_tie_before_returning_any_creatures():
    engine = game(players=3)
    candidates = {p: [filler(engine, f"{p} Choice {i}", mv=5, power=i+2, toughness=5, player=p)
                      for i in range(2)] for p in ("p2", "p3")}
    cheap = filler(engine, "Cheap", mv=1, power=1, toughness=1, player="p2")
    card(engine, "Summon: Valefor")
    engine.resolve_until_stable()
    first_choice = engine.state.pending_choice
    assert first_choice["player_id"] == "p2"
    assert {o["instance_id"] for o in first_choice["options"]} == {o.instance_id for o in candidates["p2"]}
    engine.resolve_pending_choice(candidates["p2"][1].instance_id)
    assert engine.state.pending_choice["player_id"] == "p3"
    assert all(o.zone == Zone.BATTLEFIELD for values in candidates.values() for o in values)
    engine.resolve_pending_choice(candidates["p3"][0].instance_id)
    assert candidates["p2"][1].zone == candidates["p3"][0].zone == Zone.HAND
    assert candidates["p2"][0].zone == candidates["p3"][1].zone == cheap.zone == Zone.BATTLEFIELD

"""PAR-287 milestone 4: a bounded "discards X cards" row (Mind Twist family, Arcane Omens, Cabal Shrine, Tormented
Thoughts), Felothar's "its power" naming the sacrificed creature, "if you can't" (Egon), "its controller gains control of
~" (Act of Authority), "for each of those creatures" (Bounding Felidar) and a source-animation "it" (the Gideons).
Real cards on a real engine; every case has a same-type bystander or the antecedent-did-not-happen path."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.deck_batch import RICH, activate, answer, attack, card, cast, filler, game, put_on_battlefield, step

NEWLY = ["Mind Twist", "Mind Shatter", "Mind Burst", "Greel, Mind Raker", "Arcane Omens", "Cabal Shrine",
         "Tormented Thoughts", "Felothar the Steadfast", "Egon, God of Death", "Act of Authority", "Bounding Felidar",
         "Gideon, Ally of Zendikar", "Gideon, Martial Paragon"]


@pytest.mark.parametrize("name", NEWLY)
def test_cards_are_modeled(name):
    assert parse_oracle(CardDatabase(DB_PATH).get_card(name)).coverage == MODELED


def _hand(engine, player, count, prefix="H"):
    return [filler(engine, f"{prefix}{player}{i}", type_line="Instant", player=player, zone=Zone.HAND) for i in range(count)]


def _gy_names(engine, player):
    return sorted(o.name for o in engine.state.player_by_id(player).graveyard)


# --- Mind Twist: X from the announced cost, random --------------------------------------------------------------------

@pytest.mark.parametrize("x,hand,expected", [(3, 5, 3), (0, 5, 0), (4, 2, 2)])
def test_mind_twist_discards_x_at_random_from_the_target_only(x, hand, expected):
    engine = game()
    mine = _hand(engine, "p1", 3, "Mine")
    theirs = _hand(engine, "p2", hand)
    spell = card(engine, "Mind Twist", zone=Zone.HAND)
    cast(engine, spell, targets=[engine.state.player_by_id("p2")], x=x)
    assert len(engine.state.player_by_id("p2").hand) == hand - expected
    assert sum(1 for o in theirs if o.zone == Zone.GRAVEYARD) == expected
    assert all(o.zone == Zone.HAND for o in mine)                       # the caster's own hand is untouched
    assert engine.state.pending_choice is None                          # "at random": nobody is asked to pick


def test_greel_activation_discards_x_at_random_after_paying_two_discards():
    engine = game()
    greel = card(engine, "Greel, Mind Raker")
    _hand(engine, "p1", 3, "Mine")
    theirs = _hand(engine, "p2", 5)
    p1 = engine.state.player_by_id("p1")
    p1.mana_pool.add_many(RICH)
    engine.state.current_phase, engine.state.current_step = "main", "main1"
    ids = [o.instance_id for o in p1.hand[:2]]
    engine.activate_ability(p1, greel, 0, targets=[engine.state.player_by_id("p2")], x=2, discard_choices=ids)
    engine.resolve_until_stable()
    assert sum(1 for o in theirs if o.zone == Zone.GRAVEYARD) == 2


# --- Mind Burst / Arcane Omens: "where X is ..." ----------------------------------------------------------------------

def test_mind_burst_counts_one_plus_burst_cards_in_all_graveyards_and_the_victim_chooses():
    engine = game()
    for player in ("p1", "p2"):                                         # same name in two different graveyards
        filler(engine, "Mind Burst", type_line="Sorcery", player=player, zone=Zone.GRAVEYARD)
    filler(engine, "Mind Twist", type_line="Sorcery", player="p2", zone=Zone.GRAVEYARD)   # different name: not counted
    theirs = _hand(engine, "p2", 5)
    spell = card(engine, "Mind Burst", zone=Zone.HAND)
    cast(engine, spell, targets=[engine.state.player_by_id("p2")])
    choice = engine.state.pending_choice
    assert choice is not None and choice["player_id"] == "p2"           # RULE 701.8: the discarding player picks
    answer(engine, pick=lambda c: next(i for i in (str(o["id"]) for o in c["options"]) if i not in
                                       {str(t.instance_id) for t in theirs if t.zone == Zone.GRAVEYARD}))
    assert sum(1 for o in theirs if o.zone == Zone.GRAVEYARD) == 1 + 2


def test_arcane_omens_discards_the_number_of_colors_spent():
    engine = game()
    theirs = _hand(engine, "p2", 5)
    spell = card(engine, "Arcane Omens", zone=Zone.HAND)
    cast(engine, spell, pool={"B": 1, "R": 4}, targets=[engine.state.player_by_id("p2")])
    answer(engine)
    assert sum(1 for o in theirs if o.zone == Zone.GRAVEYARD) == 2     # black and red, not five mana


# --- Cabal Shrine -----------------------------------------------------------------------------------------------------

def test_cabal_shrine_makes_the_caster_discard_one_per_same_named_graveyard_card():
    engine = game()
    card(engine, "Cabal Shrine")
    for player in ("p1", "p2"):
        filler(engine, "Opt", type_line="Instant", player=player, zone=Zone.GRAVEYARD)
    filler(engine, "Shock", type_line="Instant", player="p2", zone=Zone.GRAVEYARD)         # different name: not counted
    theirs = _hand(engine, "p2", 4)
    mine = _hand(engine, "p1", 4, "Mine")
    spell = card(engine, "Opt", player="p2", zone=Zone.HAND)
    cast(engine, spell)
    answer(engine)
    assert sum(1 for o in theirs if o.zone == Zone.GRAVEYARD) == 2   # "that player" = the caster, not the Shrine's owner
    assert all(o.zone == Zone.HAND for o in mine)


# --- Tormented Thoughts / Felothar: the sacrificed creature's last-known stats --------------------------------------

def test_tormented_thoughts_discards_the_sacrificed_creatures_power_not_a_bystanders():
    engine = game()
    victim = filler(engine, "Victim", type_line="Creature — Ogre", power=3, toughness=1)
    filler(engine, "Bystander", type_line="Creature — Ogre", power=6, toughness=6)
    theirs = _hand(engine, "p2", 6)
    spell = card(engine, "Tormented Thoughts", zone=Zone.HAND)
    cast(engine, spell, targets=[engine.state.player_by_id("p2")], sacrifice_choice=victim.instance_id)
    answer(engine)
    assert victim.zone == Zone.GRAVEYARD
    assert sum(1 for o in theirs if o.zone == Zone.GRAVEYARD) == 3


def _felothar_run(victim_power, victim_toughness):
    engine = game(library=20)
    felothar = card(engine, "Felothar the Steadfast")
    victim = filler(engine, "Victim", type_line="Creature — Ogre", power=victim_power, toughness=victim_toughness)
    filler(engine, "Bystander", type_line="Creature — Ogre", power=9, toughness=9)
    p1 = engine.state.player_by_id("p1")
    _hand(engine, "p1", 8, "Mine")
    before = len(p1.hand)
    p1.mana_pool.add_many({"C": 3})
    engine.state.current_phase, engine.state.current_step = "main", "main1"
    engine.activate_ability(p1, felothar, 0, sacrifice_choice=victim.instance_id)
    engine.resolve_until_stable()
    answer(engine)
    return engine, felothar, p1, len(p1.hand) - before


def test_felothar_draws_toughness_then_discards_the_sacrificed_creatures_power():
    engine, felothar, p1, delta = _felothar_run(victim_power=2, victim_toughness=4)
    assert delta == 4 - 2                                  # not Felothar's own (or the bystander's) power
    assert sum(1 for o in p1.graveyard if o.name.startswith("Mine")) == 2


def test_felothar_with_zero_power_victim_discards_nothing():
    engine, felothar, p1, delta = _felothar_run(victim_power=0, victim_toughness=3)
    assert delta == 3
    assert not any(o.name.startswith("Mine") for o in p1.graveyard)


# --- Egon: "if you can't" ---------------------------------------------------------------------------------------------

def _egon_upkeep(graveyard_cards):
    engine = game()
    egon = card(engine, "Egon, God of Death")
    for i in range(graveyard_cards):
        filler(engine, f"G{i}", type_line="Creature", zone=Zone.GRAVEYARD)
    p1 = engine.state.player_by_id("p1")
    hand_before = len(p1.hand)
    step(engine, "upkeep")
    for _ in range(4):
        if engine.state.pending_choice is None:
            break
        answer(engine, limit=1)
        engine.resolve_until_stable()
    return engine, egon, p1, len(p1.hand) - hand_before


def test_egon_exiles_two_graveyard_cards_and_keeps_itself():
    engine, egon, p1, drawn = _egon_upkeep(3)
    assert egon.zone == Zone.BATTLEFIELD and drawn == 0
    assert len([o for o in p1.graveyard if o.name.startswith("G")]) == 1      # three there, two were exiled


@pytest.mark.parametrize("graveyard_cards", [1, 0])
def test_egon_sacrifices_itself_and_draws_when_it_cannot_exile_two(graveyard_cards):
    engine, egon, p1, drawn = _egon_upkeep(graveyard_cards)
    assert egon.zone == Zone.GRAVEYARD and drawn == 1
    assert len([o for o in p1.graveyard if o.name.startswith("G")]) == graveyard_cards   # nothing was exiled


# --- Act of Authority: "its controller gains control of ~" ------------------------------------------------------------

def _authority_upkeep(target_name, target_owner, target_controller, answer_yes):
    engine = game()
    target = filler(engine, target_name, type_line="Artifact", player=target_owner)
    target.controller_id = target_controller
    bystander = filler(engine, "Bystander", type_line="Artifact", player="p2")
    authority = put_on_battlefield(engine, "Act of Authority")
    engine.resolve_pending_choice("decline")                           # the enters trigger's optional target
    step(engine, "upkeep")
    engine.resolve_pending_choice(str(target.instance_id))
    engine.resolve_pending_choice("yes" if answer_yes else "decline")
    engine.resolve_until_stable()
    return engine, authority, target, bystander


def test_act_of_authority_goes_to_the_exiled_permanents_controller():
    engine, authority, target, bystander = _authority_upkeep("Rock", "p2", "p2", True)
    assert target.zone == Zone.EXILE and bystander.zone == Zone.BATTLEFIELD
    assert authority.controller_id == "p2"


def test_act_of_authority_reads_the_controller_not_the_owner_of_the_exiled_permanent():
    engine, authority, target, _ = _authority_upkeep("Stolen Rock", "p1", "p2", True)   # p1 owns it, p2 controls it
    assert target.zone == Zone.EXILE
    assert authority.controller_id == "p2"


def test_act_of_authority_goes_to_the_exiled_controller_not_the_next_opponent_in_seat_order():
    engine = game(players=3)
    target = filler(engine, "Rock", type_line="Artifact", player="p3")
    authority = put_on_battlefield(engine, "Act of Authority")
    engine.resolve_pending_choice("decline")
    step(engine, "upkeep")
    engine.resolve_pending_choice(str(target.instance_id))
    engine.resolve_pending_choice("yes")
    engine.resolve_until_stable()
    assert target.zone == Zone.EXILE and authority.controller_id == "p3"      # p2 is the next seat; p3 controlled the Rock


def test_act_of_authority_declined_keeps_everything():
    engine, authority, target, _ = _authority_upkeep("Rock", "p2", "p2", False)
    assert target.zone == Zone.BATTLEFIELD and authority.controller_id == "p1"


def test_act_of_authority_exiling_your_own_permanent_changes_no_control():
    engine, authority, target, _ = _authority_upkeep("Own Rock", "p1", "p1", True)
    assert target.zone == Zone.EXILE and authority.controller_id == "p1"


# --- Bounding Felidar: "for each of those creatures" ------------------------------------------------------------------

def _felidar_attack(extra_creatures, prohibited=False):
    engine = game()
    felidar = card(engine, "Bounding Felidar")
    bodies = [filler(engine, f"Body{i}", type_line="Creature — Cat", power=1, toughness=1) for i in range(extra_creatures)]
    filler(engine, "Theirs", type_line="Creature — Cat", player="p2", power=1, toughness=1)   # not "you control"
    felidar.saddled_until_turn = engine.state.internal_turn.number     # RULE 702.171: saddled this turn
    life = engine.state.player_by_id("p1").life
    attack(engine, [felidar])
    return engine, felidar, bodies, engine.state.player_by_id("p1").life - life


def test_bounding_felidar_gains_life_per_creature_that_got_a_counter():
    engine, felidar, bodies, gained = _felidar_attack(2)
    assert all(b.plus_one_counters == 1 for b in bodies)
    assert gained == 2                                                  # the two others, not Felidar and not their creature


def test_bounding_felidar_alone_gains_nothing():
    engine, felidar, bodies, gained = _felidar_attack(0)
    assert gained == 0


# --- The Gideons: "it" after "~ becomes ..." is still the planeswalker ------------------------------------------------

def test_gideon_animation_prevents_damage_to_gideon_only():
    engine = game()
    gideon = card(engine, "Gideon, Ally of Zendikar")
    bystander = filler(engine, "Bystander", type_line="Creature — Ogre", power=2, toughness=9)
    shooter = filler(engine, "Shooter", type_line="Creature", player="p2", power=1, toughness=1)
    activate(engine, gideon, 0)
    assert "Creature" in gideon.card.type_line or gideon.is_creature          # animated this turn
    loyalty = gideon.loyalty
    engine.rules.deal_damage(gideon, 3, source=shooter)
    engine.rules.deal_damage(bystander, 3, source=shooter)
    assert gideon.damage_marked == 0 and gideon.loyalty == loyalty              # "it" (Gideon) is protected
    assert bystander.damage_marked == 3                                                 # a same-type bystander is not


# --- Cards the "if you can't" / "its controller" / "its toughness" rows claimed beyond the target list ------------------

EXTRA = ["Contested War Zone", "Inventive Iteration // Living Breakthrough", "Momentous Fall", "Patient Naturalist",
         "Roots of Wisdom", "Temp of the Damned", "Temporal Conqueror"]


@pytest.mark.parametrize("name", EXTRA)
def test_extra_claimed_cards_are_modeled(name):
    assert parse_oracle(CardDatabase(DB_PATH).get_card(name)).coverage == MODELED


def _top_of_library(engine, *names, type_line="Creature"):
    from tests.support.deck_batch import stack_library
    stack_library(engine, "p1", *[filler(engine, n, type_line=type_line, zone=Zone.LIBRARY) for n in names])


def _treasures(engine):
    return [o for o in engine.state.battlefield if o.name == "Treasure"]


@pytest.mark.parametrize("name", ["Patient Naturalist", "Temporal Conqueror"])
def test_milling_a_land_returns_it_and_makes_no_treasure(name):
    engine = game()
    engine.state.player_by_id("p1").library[:] = []
    _top_of_library(engine, "Spell A", "Spell B")
    _top_of_library(engine, "Milled Land", type_line="Land")
    put_on_battlefield(engine, name)
    answer(engine)
    p1 = engine.state.player_by_id("p1")
    assert any(o.name == "Milled Land" for o in p1.hand)
    assert not _treasures(engine)


@pytest.mark.parametrize("name", ["Patient Naturalist", "Temporal Conqueror"])
def test_milling_no_land_makes_a_treasure(name):
    engine = game()
    engine.state.player_by_id("p1").library[:] = []
    _top_of_library(engine, "Spell A", "Spell B", "Spell C")
    put_on_battlefield(engine, name)
    answer(engine)
    p1 = engine.state.player_by_id("p1")
    assert not any(o.card.is_land for o in p1.hand)
    assert len(_treasures(engine)) == 1


def test_roots_of_wisdom_draws_only_when_no_land_or_elf_could_return():
    engine = game()
    engine.state.player_by_id("p1").library[:] = []
    _top_of_library(engine, "Spell A", "Spell B", "Spell C", "Spell D")
    filler(engine, "Dead Elf", type_line="Creature — Elf", zone=Zone.GRAVEYARD)
    filler(engine, "Dead Ogre", type_line="Creature — Ogre", zone=Zone.GRAVEYARD)      # the same-type bystander
    p1 = engine.state.player_by_id("p1")
    spell = card(engine, "Roots of Wisdom", zone=Zone.HAND)
    cast(engine, spell)
    answer(engine)
    assert [o.name for o in p1.hand] == ["Dead Elf"]                                    # returned, so no draw

    engine2 = game()
    engine2.state.player_by_id("p1").library[:] = []
    _top_of_library(engine2, "Spell A", "Spell B", "Spell C", "Spell D")
    filler(engine2, "Dead Ogre", type_line="Creature — Ogre", zone=Zone.GRAVEYARD)
    spell2 = card(engine2, "Roots of Wisdom", zone=Zone.HAND)
    cast(engine2, spell2)
    answer(engine2)
    hand2 = engine2.state.player_by_id("p1").hand
    assert len(hand2) == 1 and hand2[0].name != "Dead Ogre"                              # nothing returned: drew the top card


@pytest.mark.parametrize("counters,survives", [(2, True), (0, False)])
def test_temp_of_the_damned_removes_a_counter_or_is_sacrificed(counters, survives):
    engine = game()
    temp = card(engine, "Temp of the Damned")
    temp.add_counters("funk", counters)
    step(engine, "upkeep")
    answer(engine)
    assert (temp.zone == Zone.BATTLEFIELD) is survives
    if survives:
        assert temp.counters.get("funk", 0) == counters - 1


def _inventive_iteration_chapter_two(artifacts_in_graveyard):
    engine = game(library=20)
    for i in range(artifacts_in_graveyard):
        filler(engine, f"Dead Rock{i}", type_line="Artifact", zone=Zone.GRAVEYARD)
    filler(engine, "Dead Ogre", type_line="Creature — Ogre", zone=Zone.GRAVEYARD)       # the same-zone bystander
    saga = put_on_battlefield(engine, "Inventive Iteration // Living Breakthrough")
    answer(engine)                                                                        # chapter I: decline the bounce
    p1 = engine.state.player_by_id("p1")
    hand = len(p1.hand)
    engine.rules.add_counters(saga, 1, "lore")                                                  # RULE 714.2: chapter II
    engine.resolve_until_stable()
    answer(engine)
    return engine, p1, len(p1.hand) - hand


def test_inventive_iteration_chapter_two_returns_an_artifact_and_does_not_draw():
    engine, p1, gained = _inventive_iteration_chapter_two(1)
    assert gained == 1 and any(o.name == "Dead Rock0" for o in p1.hand)
    assert not any(o.name == "Dead Ogre" for o in p1.hand)


def test_inventive_iteration_chapter_two_draws_when_no_artifact_card_is_there():
    engine, p1, gained = _inventive_iteration_chapter_two(0)
    assert gained == 1 and not any(o.name == "Dead Ogre" for o in p1.hand)               # drew the top card, returned nothing


def test_momentous_fall_draws_the_sacrificed_power_and_gains_its_toughness():
    engine = game(library=20)
    victim = filler(engine, "Victim", type_line="Creature — Ogre", power=2, toughness=5)
    filler(engine, "Bystander", type_line="Creature — Ogre", power=8, toughness=8)
    p1 = engine.state.player_by_id("p1")
    life, hand = p1.life, len(p1.hand)
    spell = card(engine, "Momentous Fall", zone=Zone.HAND)
    cast(engine, spell, sacrifice_choice=victim.instance_id)
    assert len(p1.hand) - hand == 2 and p1.life - life == 5


def test_contested_war_zone_goes_to_the_controller_of_the_creature_that_hit_you():
    engine = game()
    zone = card(engine, "Contested War Zone")
    attacker = filler(engine, "Raider", type_line="Creature — Ogre", player="p2", power=2, toughness=2)
    filler(engine, "Other Raider", type_line="Creature — Ogre", player="p2", power=1, toughness=1)
    engine.state.active_player_id = "p2"
    engine.state.fire_event(__import__("mtg_analyzer.models.game.events", fromlist=["GameEvent"]).GameEvent(
        "DAMAGE", source_id=attacker.instance_id, target_id="p1", is_player=True, amount=2, combat=True,
        controller_id="p2", source_controller_id="p2"))
    engine.resolve_until_stable()
    assert zone.controller_id == "p2"

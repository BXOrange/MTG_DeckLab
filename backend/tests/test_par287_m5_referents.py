"""PAR-287 milestone 5: counters-put payloads (Bioessence Hydra, Lonis), a target player's group shared across two group
steps (Great Oak Guardian, Trystan's Command), a mill between a chosen creature and its pronoun (Drown in Filth, Grave
Strength, Glacial Grasp) and "+0/+X where X is its mana value" on the chosen creature (Subdue, Kry Shield). Real cards
on a real engine; each case has a same-type bystander or the antecedent-did-not-happen path."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.deck_batch import RICH, activate, answer, card, cast, filler, game, named, put_on_battlefield

NEWLY = ["Bioessence Hydra", "Lonis, Genetics Expert", "Great Oak Guardian", "Trystan's Command", "Drown in Filth",
         "Grave Strength", "Glacial Grasp", "Subdue", "Kry Shield", "Kitsune Loreweaver", "Simic Ascendancy"]


@pytest.mark.parametrize("name", NEWLY)
def test_cards_are_modeled(name):
    assert parse_oracle(CardDatabase(DB_PATH).get_card(name)).coverage == MODELED


def _planeswalker(engine, name, player):
    return card(engine, name, player)


def _plus_counters(obj):
    return obj.counters.get("+1/+1", 0)


# --- Bioessence Hydra: "that many" is the loyalty counters that landed -------------------------------------------------

def test_hydra_gets_as_many_counters_as_loyalty_counters_put_on_my_planeswalkers():
    engine = game()
    hydra = card(engine, "Bioessence Hydra")
    mine = _planeswalker(engine, "Jace Beleren", "p1")
    engine.rules.add_counters(mine, 3, "loyalty")
    engine.resolve_until_stable()
    assert _plus_counters(hydra) == 3
    engine.rules.add_counters(mine, 2, "loyalty")
    engine.resolve_until_stable()
    assert _plus_counters(hydra) == 5                                    # each placement is its own payload


def test_hydra_ignores_an_opponents_planeswalker_other_counters_and_creatures():
    engine = game()
    hydra = card(engine, "Bioessence Hydra")
    theirs = _planeswalker(engine, "Chandra Nalaar", "p2")
    mine = _planeswalker(engine, "Jace Beleren", "p1")
    bystander = filler(engine, "Bystander", power=1, toughness=1)
    engine.rules.add_counters(theirs, 4, "loyalty")                           # not "planeswalkers you control"
    engine.rules.add_counters(mine, 4, "charge")                              # not loyalty counters
    engine.rules.add_counters(bystander, 4, "loyalty")                        # not a planeswalker
    engine.resolve_until_stable()
    assert _plus_counters(hydra) == 0
    assert _plus_counters(bystander) == 0 and _plus_counters(theirs) == 0


# --- Lonis: "investigate that many times" -------------------------------------------------------------------------------

def test_lonis_investigates_once_per_counter_put_on_itself_only():
    engine = game()
    lonis = card(engine, "Lonis, Genetics Expert")
    other = filler(engine, "Bystander", power=1, toughness=1)
    engine.rules.add_counters(other, 3, "+1/+1")                              # a bystander's counters do not count
    engine.rules.add_counters(lonis, 2, "charge")                             # nor does another kind on Lonis
    engine.resolve_until_stable()
    assert not named(engine, "Clue")
    engine.rules.add_counters(lonis, 3, "+1/+1")
    engine.resolve_until_stable()
    assert len(named(engine, "Clue")) == 3
    engine.rules.add_counters(lonis, 1, "+1/+1")
    engine.resolve_until_stable()
    assert len(named(engine, "Clue")) == 4


# --- Great Oak Guardian / Trystan's Command: one target player, two group steps -------------------------------------------

def _board(engine):
    mine = filler(engine, "MineA", power=1, toughness=1)
    mine_tapped = filler(engine, "MineB", power=1, toughness=1)
    theirs = [filler(engine, f"Theirs{i}", power=2, toughness=2, player="p2") for i in range(2)]
    for obj in (mine_tapped, *theirs):
        obj.tapped = True
    return mine, mine_tapped, theirs


@pytest.mark.parametrize("victim,friend", [("p2", "p1"), ("p1", "p2")])
def test_great_oak_guardian_pumps_and_untaps_only_the_target_players_creatures(victim, friend):
    engine = game()
    mine, mine_tapped, theirs = _board(engine)
    owned = {"p1": [mine, mine_tapped], "p2": theirs}
    before = {o.instance_id: (o.power, o.tapped) for objs in owned.values() for o in objs}
    cast(engine, card(engine, "Great Oak Guardian", zone=Zone.HAND))
    answer(engine, pick=lambda c: victim if victim in {str(o["id"]) for o in c["options"]} else None)
    engine.resolve_until_stable()
    for obj in owned[victim]:
        assert obj.power == before[obj.instance_id][0] + 2 and not obj.tapped
    for obj in owned[friend]:                                           # the bystanders keep power and tapped state
        assert (obj.power, obj.tapped) == before[obj.instance_id]


def test_great_oak_guardian_aimed_at_a_player_without_creatures_leaves_the_casters_alone():
    engine = game()
    mine, mine_tapped, theirs = _board(engine)
    for obj in theirs:
        engine.state.battlefield.remove(obj)
    cast(engine, card(engine, "Great Oak Guardian", zone=Zone.HAND))
    answer(engine, pick=lambda c: "p2" if "p2" in {str(o["id"]) for o in c["options"]} else None)
    assert mine.power == 1 and mine_tapped.tapped


def test_trystans_command_group_mode_pumps_and_untaps_the_target_players_creatures_only():
    engine = game()
    mine, mine_tapped, theirs = _board(engine)
    doomed = filler(engine, "Doomed", power=1, toughness=1, player="p2")
    spell = card(engine, "Trystan's Command", zone=Zone.HAND)
    # Mode 2 destroys one creature, mode 3 is the group step (RULE 700.2: the player is that mode's own target).
    cast(engine, spell, targets=[doomed, engine.state.player_by_id("p2")], mode=[2, 3])
    assert doomed.zone == Zone.GRAVEYARD
    assert all(o.power == 5 and o.toughness == 5 and not o.tapped for o in theirs)   # +3/+3 and untapped
    assert (mine.power, mine_tapped.power, mine_tapped.tapped) == (1, 1, True)       # the caster's creatures: untouched


# --- Drown in Filth / Grave Strength: a mill between the chosen creature and "that creature" -----------------------------

def _graveyard_cards(engine, count, type_line, player="p1"):
    return [filler(engine, f"G{type_line}{i}", type_line=type_line, player=player, zone=Zone.GRAVEYARD)
            for i in range(count)]


def test_drown_in_filth_counts_lands_after_the_mill_and_shrinks_only_the_chosen_creature():
    engine = game()
    victim = filler(engine, "Victim", power=9, toughness=9, player="p2")
    bystander = filler(engine, "Bystander", power=9, toughness=9, player="p2")
    _graveyard_cards(engine, 2, "Land")                                 # already there: counted with the milled ones
    cast(engine, card(engine, "Drown in Filth", zone=Zone.HAND), targets=[victim])
    lands = sum(1 for o in engine.state.player_by_id("p1").graveyard if o.card.is_land)
    assert lands == 2 + 4                                               # mill 4 first, then count
    assert (victim.power, victim.toughness) == (9 - lands, 9 - lands)
    assert (bystander.power, bystander.toughness) == (9, 9)


def test_grave_strength_counts_creature_cards_after_the_mill_and_buffs_only_the_chosen_creature():
    engine = game()
    chosen = filler(engine, "Chosen", power=1, toughness=1)
    bystander = filler(engine, "Bystander", power=1, toughness=1)
    _graveyard_cards(engine, 2, "Creature")
    cast(engine, card(engine, "Grave Strength", zone=Zone.HAND), targets=[chosen])
    assert _plus_counters(chosen) == 2 and _plus_counters(bystander) == 0   # the milled Forests are not creature cards


def test_grave_strength_with_no_creature_card_in_the_graveyard_puts_nothing():
    engine = game()
    chosen = filler(engine, "Chosen", power=1, toughness=1)
    cast(engine, card(engine, "Grave Strength", zone=Zone.HAND), targets=[chosen])
    assert _plus_counters(chosen) == 0


# --- Glacial Grasp: tap, its controller mills, that creature stays tapped --------------------------------------------------

def test_glacial_grasp_taps_the_target_mills_its_controller_and_freezes_only_that_creature():
    engine = game()
    victim = filler(engine, "Victim", power=2, toughness=2, player="p2")
    bystander = filler(engine, "Bystander", power=2, toughness=2, player="p2")
    bystander.tapped = True
    mine = len(engine.state.player_by_id("p1").library)
    theirs = len(engine.state.player_by_id("p2").library)
    cast(engine, card(engine, "Glacial Grasp", zone=Zone.HAND), targets=[victim])
    assert victim.tapped and victim.skip_next_untap and not bystander.skip_next_untap
    assert len(engine.state.player_by_id("p2").library) == theirs - 2    # its controller mills, not the caster
    assert len(engine.state.player_by_id("p1").library) == mine - 1   # only the printed "Draw a card"
    engine.state.active_player_index = 1                                 # p2's untap step
    engine._step_untap()
    assert victim.tapped and not bystander.tapped


# --- Subdue / Kry Shield: "+0/+X where X is its mana value" is the chosen creature's --------------------------------------

def test_subdue_adds_the_chosen_creatures_mana_value_to_its_toughness_only():
    engine = game()
    chosen = filler(engine, "Chosen", power=1, toughness=1, mv=4, player="p2")
    bystander = filler(engine, "Bystander", power=1, toughness=1, mv=7, player="p2")
    cast(engine, card(engine, "Subdue", zone=Zone.HAND), targets=[chosen])
    assert (chosen.power, chosen.toughness) == (1, 1 + 4)
    assert (bystander.power, bystander.toughness) == (1, 1)


def test_kry_shield_reads_the_mana_value_of_the_creature_it_targets():
    engine = game()
    chosen = filler(engine, "Chosen", power=1, toughness=1, mv=3)
    filler(engine, "Bystander", power=1, toughness=1, mv=6)
    shield = card(engine, "Kry Shield")
    engine.state.player_by_id("p1").mana_pool.add_many(RICH)
    activate(engine, shield, targets=[chosen])
    assert chosen.toughness == 1 + 3 and shield.tapped


def test_kitsune_loreweaver_pumps_only_itself_by_the_cards_in_its_controllers_hand():
    engine = game()
    kitsune = card(engine, "Kitsune Loreweaver")
    bystander = filler(engine, "Bystander", power=1, toughness=1)
    for i in range(3):
        filler(engine, f"Held{i}", type_line="Instant", zone=Zone.HAND)
    filler(engine, "TheirHand", type_line="Instant", player="p2", zone=Zone.HAND)
    base = kitsune.toughness
    engine.state.player_by_id("p1").mana_pool.add_many(RICH)
    activate(engine, kitsune)
    assert kitsune.toughness == base + 3 and bystander.toughness == 1


# --- The Advocate cycle: "from an opponent's graveyard to their hand" is the owner's hand --------------------------------

ADVOCATES = ["Forcemage Advocate", "Nullmage Advocate", "Pulsemage Advocate", "Spurnmage Advocate"]


@pytest.mark.parametrize("name", ADVOCATES)
def test_advocates_are_modeled(name):
    assert parse_oracle(CardDatabase(DB_PATH).get_card(name)).coverage == MODELED


def test_spurnmage_advocate_returns_two_cards_to_their_owners_hand_and_destroys_the_attacker():
    engine = game()
    advocate = card(engine, "Spurnmage Advocate")
    chosen = [filler(engine, f"Theirs{i}", type_line="Instant", player="p2", zone=Zone.GRAVEYARD) for i in range(2)]
    left = filler(engine, "TheirsLeft", type_line="Instant", player="p2", zone=Zone.GRAVEYARD)
    mine = filler(engine, "Mine", type_line="Instant", player="p1", zone=Zone.GRAVEYARD)
    attacker = filler(engine, "Attacker", power=2, toughness=2, player="p2")
    attacker.attacking = True
    bystander = filler(engine, "Bystander", power=2, toughness=2, player="p2")
    activate(engine, advocate, targets=[*chosen, attacker])
    assert all(o.zone == Zone.HAND and o in engine.state.player_by_id("p2").hand for o in chosen)   # the owner's hand
    assert not engine.state.player_by_id("p1").hand                                               # the caster gets none
    assert left.zone == Zone.GRAVEYARD and mine.zone == Zone.GRAVEYARD                              # not chosen / not theirs
    assert attacker.zone == Zone.GRAVEYARD and bystander.zone == Zone.BATTLEFIELD


def test_their_hand_is_only_read_for_an_opponents_graveyard():
    import copy

    base = CardDatabase(DB_PATH).get_card("Forcemage Advocate")
    for scope, expected in (("an opponent's", True), ("a", False), ("your", False)):
        probe = copy.copy(base)
        probe.oracle_text = f"{{T}}: Return target card from {scope} graveyard to their hand."
        assert (parse_oracle(probe).coverage == MODELED) is expected, scope


# --- "If C, you may <cost>. If you do, <effect>": the gate belongs to the payment, the payoff follows a paid cost ----------

GATED_PAYMENT = ["Take Out the Trash", "Chandra's Defeat", "Taborax, Hope's Demise"]


@pytest.mark.parametrize("name", GATED_PAYMENT)
def test_gated_payment_cards_are_modeled(name):
    assert parse_oracle(CardDatabase(DB_PATH).get_card(name)).coverage == MODELED


@pytest.mark.parametrize("raccoon,pay,drawn", [(True, True, True), (True, False, False), (False, True, False)])
def test_take_out_the_trash_offers_the_discard_only_with_a_raccoon_and_draws_only_after_paying(raccoon, pay, drawn):
    engine = game()
    victim = filler(engine, "Victim", power=2, toughness=5, player="p2")
    if raccoon:
        filler(engine, "Rac", type_line="Creature — Raccoon", power=1, toughness=1)
    held = filler(engine, "Held", type_line="Instant", zone=Zone.HAND)
    p1 = engine.state.player_by_id("p1")
    cast(engine, card(engine, "Take Out the Trash", zone=Zone.HAND), targets=[victim])
    assert (engine.state.pending_choice is not None) is raccoon          # no Raccoon: no discard is even offered
    answer(engine, pick=lambda c: "pay" if pay else "decline")
    assert victim.damage_marked == 3                                     # the damage never depended on the gate
    assert (held.zone == Zone.GRAVEYARD) is (raccoon and pay)
    assert ([o.name for o in p1.hand] == ["Forest"]) is drawn            # the draw is the payoff of a paid discard


@pytest.mark.parametrize("target_name,is_chandra", [("Chandra Nalaar", True), ("Goblin Piker", False)])
def test_chandras_defeat_offers_the_discard_only_when_the_target_is_a_chandra_planeswalker(target_name, is_chandra):
    engine = game()
    target = card(engine, target_name, "p2")                             # a red creature or a Chandra planeswalker
    held = filler(engine, "Held", type_line="Instant", zone=Zone.HAND)
    cast(engine, card(engine, "Chandra's Defeat", zone=Zone.HAND), targets=[target])
    assert (engine.state.pending_choice is not None) is is_chandra
    answer(engine, pick=lambda c: "pay")
    assert (held.zone == Zone.GRAVEYARD) is is_chandra


@pytest.mark.parametrize("dying_type,cleric", [("Creature — Cleric", True), ("Creature — Soldier", False)])
def test_taborax_loses_life_only_after_it_drew_and_only_for_a_dying_cleric(dying_type, cleric):
    engine = game()
    taborax = card(engine, "Taborax, Hope's Demise")
    victim = filler(engine, "Victim", type_line=dying_type, power=1, toughness=1)
    before = engine.state.player_by_id("p1").life
    engine.rules.deal_damage(victim, 5, source=taborax, combat=False)
    engine.resolve_until_stable()
    answer(engine, pick=lambda c: "pay" if "pay" in {str(o["id"]) for o in c["options"]} else str(c["options"][0]["id"]))
    assert taborax.counters.get("+1/+1") == 1                            # the counter does not depend on the type
    assert (engine.state.player_by_id("p1").life == before - 1) is cleric


# --- "that opponent" under an opponent-damage head is the damaged player ------------------------------------------------

@pytest.mark.parametrize("name,controller_draws", [("Zhang Liao, Hero of Hefei", 0), ("Fungal Shambler", 1)])
@pytest.mark.parametrize("damaged,other", [("p3", "p2"), ("p2", "p3")])
def test_that_opponent_discards_is_the_damaged_opponent_only(name, controller_draws, damaged, other):
    assert parse_oracle(CardDatabase(DB_PATH).get_card(name)).coverage == MODELED
    engine = game(players=3, library=6)
    source = card(engine, name)
    for pid in ("p1", "p2", "p3"):
        for i in range(3):
            filler(engine, f"Card {pid}{i}", type_line="Instant", player=pid, zone=Zone.HAND)
    hands = {p.id: len(p.hand) for p in engine.state.players}
    engine.rules.deal_damage(engine.state.player_by_id(damaged), 2, source=source, combat=False)
    engine.resolve_until_stable()
    answer(engine)
    after = {p.id: len(p.hand) for p in engine.state.players}
    assert after[damaged] == hands[damaged] - 1                          # the damaged opponent discards
    assert after[other] == hands[other]                                  # not the other opponent
    assert after["p1"] == hands["p1"] + controller_draws                 # the controller discards nothing; Shambler draws

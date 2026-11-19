"""PAR-286 milestone 10: keyword-action event heads, "plays a card", enchantment-animating state triggers,
qualified tap-N costs, a first-name trigger subject and die heads.

Every behaviour test drives the real event (or pays the real cost) on the real cached card, next to a near miss that
must not fire or pay.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.card_registry import is_registered
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.normalize import normalize
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.deck_batch import activate, answer, card, cast, enter, filler, game, main_phase, named, stack_library

#: (name, whether it was already hand-authored: those are counted separately and not claimed as new coverage)
NEWLY_MODELED = [
    "Pia Nalaar, Consul of Revival",
    "Renegade Krasis", "Iron Monger, Sadistic Tycoon", "Valeron Wardens", "Stubborn Burrowfiend",
    "Null Profusion", "Recycle", "Juju Bubble",
    "Hidden Herd", "Hidden Predators", "Lurking Jackals", "Veiled Crocodile",
    "Sky Hussar", "Templar Knight", "The Cookout Creator",
    "Elanor Gardner", "Tarkiran Towelsbane", "Hurska Sweet-Tooth",
    "Resolute Veggiesaur", "Critical Hit", "Chicken à la King",
]


@pytest.mark.parametrize("name", NEWLY_MODELED)
def test_card_is_modeled(name):
    card_ = CardDatabase(DB_PATH).get_card(name)
    assert card_ is not None
    assert parse_oracle(card_).coverage == MODELED


def _events(engine, event_type):
    return [e for e in engine.state.event_log if e.type == event_type]


def _counters(obj):
    return (obj.counters or {}).get("+1/+1", 0)


# --- evolves -------------------------------------------------------------------------------------------------------


def test_renegade_krasis_spreads_counters_only_when_it_evolves():
    engine = game()
    krasis = card(engine, "Renegade Krasis")  # 3/2
    grown = filler(engine, "Grown", power=1, toughness=1)
    grown.counters["+1/+1"] = 1
    plain = filler(engine, "Plain", power=1, toughness=1)
    engine.recompute_continuous_effects()
    # near miss: a creature with neither greater power nor greater toughness does not evolve it
    enter(engine, filler(engine, "Small", power=1, toughness=1))
    assert _events(engine, EventType.EVOLVES) == []
    assert _counters(krasis) == 0 and _counters(grown) == 1
    # a creature with greater power evolves it: the counter, then "whenever ~ evolves" reaches the *other* countered one
    enter(engine, filler(engine, "Big", power=5, toughness=5))
    assert len(_events(engine, EventType.EVOLVES)) == 1
    assert _counters(krasis) == 1
    assert _counters(grown) == 2
    assert _counters(plain) == 0


# --- connives ------------------------------------------------------------------------------------------------------


def _bolt_twice(engine, player="p1"):
    """Two spells in one turn: Ledger Shredder's "second spell each turn" connive trigger."""
    target = engine.state.player_by_id("p2" if player == "p1" else "p1")
    cast(engine, card(engine, "Lightning Bolt", player=player, zone=Zone.HAND), targets=[target])
    cast(engine, card(engine, "Lightning Bolt", player=player, zone=Zone.HAND), targets=[target])


def test_iron_monger_grows_villains_when_a_creature_i_control_connives_not_an_opponents():
    engine = game()
    monger = card(engine, "Iron Monger, Sadistic Tycoon")  # a Villain
    card(engine, "Ledger Shredder")
    _bolt_twice(engine)
    answer(engine)  # the connive discard (any card)
    assert len(_events(engine, EventType.CONNIVES)) == 1
    assert _counters(monger) == 1
    # near miss: the opponent's creature conniving does not trigger my Iron Monger
    engine2 = game()
    monger2 = card(engine2, "Iron Monger, Sadistic Tycoon")
    card(engine2, "Ledger Shredder", player="p2")
    _bolt_twice(engine2, player="p2")
    answer(engine2)
    assert len(_events(engine2, EventType.CONNIVES)) == 1
    assert _counters(monger2) == 0


def test_connive_event_waits_for_the_discard_and_its_counter():
    engine = game()
    shredder = card(engine, "Ledger Shredder")
    # a nonland card besides the drawn Forest forces an interactive discard
    keep = card(engine, "Shock", zone=Zone.HAND)
    _bolt_twice(engine)
    assert engine.state.pending_choice is not None
    assert _events(engine, EventType.CONNIVES) == []  # RULE 701.50f: not yet connived
    assert _counters(shredder) == 0
    engine.resolve_pending_choice(str(keep.instance_id))
    engine.resolve_until_stable()
    assert len(_events(engine, EventType.CONNIVES)) == 1
    assert _counters(shredder) == 1  # a nonland card was discarded, and the event came after it
    log = [e.type for e in engine.state.event_log]
    assert log.index(EventType.CONNIVES) > max(i for i, t in enumerate(log) if t == EventType.COUNTER)


def test_connive_with_nothing_to_discard_still_connives():
    engine = game(library=0)
    card(engine, "Ledger Shredder")
    _bolt_twice(engine)
    assert engine.state.pending_choice is None
    assert len(_events(engine, EventType.CONNIVES)) == 1  # RULE 701.50f: "even if some or all of those actions were impossible"


# --- becomes renowned ----------------------------------------------------------------------------------------------


def test_valeron_wardens_draws_for_my_renowned_creature_not_an_opponents():
    engine = game()
    wardens = card(engine, "Valeron Wardens")
    theirs = card(engine, "Valeron Wardens", player="p2")
    p1 = engine.state.player_by_id("p1")
    before = len(p1.hand)
    # the opponent's creature becomes renowned: not a creature I control
    engine.rules.deal_damage(engine.state.player_by_id("p1"), 1, source=theirs, combat=True)
    engine.resolve_until_stable()
    assert theirs.renowned and len(p1.hand) == before
    # near miss: noncombat damage does not renown
    engine.rules.deal_damage(engine.state.player_by_id("p2"), 1, source=wardens, combat=False)
    engine.resolve_until_stable()
    assert not wardens.renowned and len(p1.hand) == before
    # mine deals combat damage to a player: renown, and the second ability draws
    engine.rules.deal_damage(engine.state.player_by_id("p2"), 1, source=wardens, combat=True)
    engine.resolve_until_stable()
    assert wardens.renowned
    assert len(p1.hand) == before + 1


# --- becomes saddled -----------------------------------------------------------------------------------------------


def test_stubborn_burrowfiend_triggers_on_the_first_saddle_each_turn():
    engine = game(library=30)
    mount = card(engine, "Stubborn Burrowfiend")  # saddle 2? read the printed amount off the bound ability
    saddle_index = next(i for i, a in enumerate(mount.activated_abilities) if getattr(a.cost, "saddle_power", None))
    rider = filler(engine, "Rider", power=mount.activated_abilities[saddle_index].cost.saddle_power, toughness=1)
    graveyard_before = len(engine.state.player_by_id("p1").graveyard)
    activate(engine, mount, saddle_index)
    assert len(_events(engine, EventType.BECAME_SADDLED)) == 1
    # "mill two cards": the trigger ran
    assert len(engine.state.player_by_id("p1").graveyard) >= graveyard_before + 2
    assert rider.tapped
    # near miss: a creature that is merely tapped for something else never fires BECAME_SADDLED
    assert len(_events(engine, EventType.BECAME_SADDLED)) == 1


def _play_land(engine, player_id, name):
    """Really play a land from hand: the active player is the one playing (RULE 305.2a)."""
    player = engine.state.player_by_id(player_id)
    engine.state.active_player_index = engine.state.players.index(player)
    player.lands_played_this_turn = 0  # one land drop per call (RULE 305.2)
    main_phase(engine)
    engine.play_land(player, card(engine, name, player=player_id, zone=Zone.HAND))
    engine.resolve_until_stable()


# --- plays a card --------------------------------------------------------------------------------------------------


def test_juju_bubble_sacrifices_when_i_play_a_land_or_cast_a_spell_but_not_the_opponent():
    engine = game()
    bubble = card(engine, "Juju Bubble")
    # near miss: the opponent plays a land
    _play_land(engine, "p2", "Forest")
    engine.resolve_until_stable()
    assert bubble in engine.state.battlefield
    _play_land(engine, "p1", "Forest")
    engine.resolve_until_stable()
    assert bubble not in engine.state.battlefield
    # a cast spell is the other half of "play a card"
    engine2 = game()
    bubble2 = card(engine2, "Juju Bubble")
    cast(engine2, card(engine2, "Lightning Bolt", zone=Zone.HAND), targets=[engine2.state.player_by_id("p2")])
    assert bubble2 not in engine2.state.battlefield


# --- enchantments that animate -------------------------------------------------------------------------------------


def test_hidden_herd_animates_on_an_opponents_nonbasic_land_only():
    engine = game()
    herd = card(engine, "Hidden Herd")
    _play_land(engine, "p2", "Forest")
    engine.resolve_until_stable()
    assert not herd.is_creature  # a basic land is the near miss
    _play_land(engine, "p1", "Command Tower")
    engine.resolve_until_stable()
    assert not herd.is_creature  # my own nonbasic land is not "an opponent plays"
    _play_land(engine, "p2", "Command Tower")
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert herd.is_creature and (herd.power, herd.toughness) == (3, 3)


def test_hidden_predators_state_trigger_fires_once_and_only_for_power_four_or_more():
    engine = game()
    predators = card(engine, "Hidden Predators")
    filler(engine, "Small", player="p2", power=3, toughness=3)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert not predators.is_creature  # near miss: power 3 is not enough
    filler(engine, "Big", player="p2", power=4, toughness=4)
    engine.recompute_continuous_effects()
    engine.resolve_until_stable()
    assert predators.is_creature and (predators.power, predators.toughness) == (4, 4)
    # the intervening "if ~ is an enchantment" stops it re-triggering forever: the stack is empty and stable
    assert not engine.state.stack


def test_lurking_jackals_needs_an_opponent_at_ten_or_less_life_not_me():
    engine = game()
    jackals = card(engine, "Lurking Jackals")
    engine.state.player_by_id("p1").life = 10  # my own life is a near miss: "an opponent has"
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert not jackals.is_creature
    engine.state.player_by_id("p2").life = 10
    engine.rules.check_state_based_actions()
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert jackals.is_creature and (jackals.power, jackals.toughness) == (3, 2)


def test_veiled_crocodile_wakes_when_any_player_has_no_cards_in_hand():
    engine = game()
    croc = card(engine, "Veiled Crocodile")
    p1 = engine.state.player_by_id("p1")
    p2 = engine.state.player_by_id("p2")
    card(engine, "Forest", zone=Zone.HAND)
    card(engine, "Forest", player="p2", zone=Zone.HAND)
    engine.rules.check_state_based_actions()
    engine.resolve_until_stable()
    assert not croc.is_creature and p1.hand and p2.hand  # near miss: everyone holds a card
    p2.hand.clear()
    engine.rules.check_state_based_actions()
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert croc.is_creature and (croc.power, croc.toughness) == (4, 4)


# --- tap N untapped qualified creatures ----------------------------------------------------------------------------


def test_sky_hussar_forecast_cost_takes_white_and_or_blue_creatures_only():
    from mtg_analyzer.game.costs import parse_activation_cost

    cost = parse_activation_cost("tap 2 untapped white and/or blue creatures you control, reveal this card from your hand")
    assert cost.tap_others is not None and cost.tap_others[0] == 2
    engine = game()
    hussar = card(engine, "Sky Hussar", zone=Zone.HAND)
    player = engine.state.player_by_id("p1")
    pool = engine._tap_others_pool(player, hussar, cost.tap_others[1])
    assert pool == []
    white = card(engine, "Savannah Lions")
    blue = card(engine, "Looter il-Kor")
    red = card(engine, "Goblin Guide")
    engine.recompute_continuous_effects()
    pool = engine._tap_others_pool(player, hussar, cost.tap_others[1])
    assert {o.instance_id for o in pool} == {white.instance_id, blue.instance_id}
    assert red not in pool


def test_templar_knight_cost_takes_untapped_attacking_knights_named_itself():
    from mtg_analyzer.game.costs import parse_activation_cost

    cost = parse_activation_cost("{w}, tap 5 untapped attacking creatures you control named ~")
    assert cost.tap_others is not None and cost.tap_others[0] == 5
    engine = game()
    knights = [card(engine, "Templar Knight") for _ in range(5)]
    other = filler(engine, "Other Knight", power=1, toughness=1)
    player = engine.state.player_by_id("p1")
    assert engine._tap_others_pool(player, knights[0], cost.tap_others[1]) == []  # not attacking yet
    for k in knights + [other]:
        k.attacking = True
    pool = engine._tap_others_pool(player, knights[0], cost.tap_others[1])
    assert {o.instance_id for o in pool} == {k.instance_id for k in knights}  # the unnamed attacker is no Templar Knight
    knights[0].tapped = True
    assert knights[0] not in engine._tap_others_pool(player, knights[1], cost.tap_others[1])  # must be untapped


def test_cookout_creator_pays_by_tapping_four_humans_of_my_choice():
    engine = game()
    cookout = card(engine, "The Cookout Creator")
    humans = [filler(engine, f"Human {i}", type_line="Creature — Human", power=1, toughness=1) for i in range(5)]
    activate(engine, cookout, _activated_index(cookout), tap_choices=[h.instance_id for h in humans[:4]])
    assert [h.tapped for h in humans] == [True, True, True, True, False]
    assert len(named(engine, "Treasure")) == 1


def _activated_index(obj):
    return next(i for i, a in enumerate(obj.activated_abilities) if a.cost.tap_others)


# --- first-name trigger subject ------------------------------------------------------------------------------------


def test_first_name_folds_only_as_a_trigger_subject_of_a_comma_less_legendary():
    assert normalize("When Elanor enters, create a Food token.", "Elanor Gardner") == "when ~ enters, create a food token."
    # near miss: the first name elsewhere (a creature type or common word) is left alone
    assert "~" not in normalize("Other Elanor creatures get +1/+1.", "Elanor Gardner")
    assert "~" not in normalize("When another Elanor enters, draw a card.", "Elanor Gardner")


def test_elanor_gardner_makes_food_when_it_enters():
    engine = game()
    from tests.support.deck_batch import put_on_battlefield

    put_on_battlefield(engine, "Elanor Gardner")
    assert len(named(engine, "Food")) == 1


# --- dice ----------------------------------------------------------------------------------------------------------


def test_resolute_veggiesaur_counts_only_the_third_die_of_the_turn():
    engine = game()
    saur = card(engine, "Resolute Veggiesaur")
    for _ in range(2):
        engine.rules.roll_die(engine.state.player_by_id("p1"), 6)
        engine.resolve_until_stable()
    assert _counters(saur) == 0
    engine.rules.roll_die(engine.state.player_by_id("p1"), 6)
    engine.resolve_until_stable()
    assert _counters(saur) == 1
    engine.rules.roll_die(engine.state.player_by_id("p1"), 6)  # the fourth die is not the third
    engine.resolve_until_stable()
    assert _counters(saur) == 1


def test_resolute_veggiesaur_ignores_the_opponents_dice():
    engine = game()
    saur = card(engine, "Resolute Veggiesaur")
    for _ in range(3):
        engine.rules.roll_die(engine.state.player_by_id("p2"), 6)
        engine.resolve_until_stable()
    assert _counters(saur) == 0


def test_chicken_a_la_king_counts_birds_on_a_natural_six_of_a_six_sided_die():
    engine = game()
    chicken = card(engine, "Chicken à la King")
    engine.rules.random_int = lambda sides: sides - 1  # the die lands on its highest face
    engine.rules.roll_die(engine.state.player_by_id("p2"), 6)  # anyone's die counts
    engine.resolve_until_stable()
    assert _counters(chicken) == 1
    engine.rules.roll_die(engine.state.player_by_id("p1"), 20)  # near miss: a 20 on a d20 is no 6
    engine.resolve_until_stable()
    assert _counters(chicken) == 1
    engine.rules.random_int = lambda sides: 0  # a 1
    engine.rules.roll_die(engine.state.player_by_id("p1"), 6)
    engine.resolve_until_stable()
    assert _counters(chicken) == 1


def test_critical_hit_comes_back_from_the_graveyard_on_my_natural_twenty():
    engine = game()
    hit = card(engine, "Critical Hit", zone=Zone.GRAVEYARD)
    engine.rules.random_int = lambda sides: 0  # a 1: near miss
    engine.rules.roll_die(engine.state.player_by_id("p1"), 20)
    engine.resolve_until_stable()
    assert hit in engine.state.player_by_id("p1").graveyard
    engine.rules.random_int = lambda sides: sides - 1  # a natural 20
    engine.rules.roll_die(engine.state.player_by_id("p2"), 20)  # the opponent's roll: "when you roll"
    engine.resolve_until_stable()
    assert hit in engine.state.player_by_id("p1").graveyard
    engine.rules.roll_die(engine.state.player_by_id("p1"), 20)
    engine.resolve_until_stable()
    assert hit in engine.state.player_by_id("p1").hand


def test_dice_tally_survives_clone_so_the_third_die_is_still_the_third():
    engine = game()
    saur = card(engine, "Resolute Veggiesaur")
    for _ in range(2):
        engine.rules.roll_die(engine.state.player_by_id("p1"), 6)
    engine.resolve_until_stable()
    clone = engine.state.clone()
    assert clone.dice_rolled_this_turn.get("p1") == 2  # derived from the cloned event log, not separate state
    assert _counters(saur) == 0


# --- cards the widened conditions also unlock (state / "as long as" readings of the same two predicates) -------------

BONUS_MODELED = [
    "Ruthless Cullblade", "Guul Draz Vampire", "Blood Baron of Vizkopa", "Vampire Lacerator", "Lupine Prototype",
    "Opal Avenger", "Ultron, Unlimited",
]


@pytest.mark.parametrize("name", BONUS_MODELED)
def test_bonus_card_is_modeled(name):
    card_ = CardDatabase(DB_PATH).get_card(name)
    assert card_ is not None
    assert parse_oracle(card_).coverage == MODELED


def test_ruthless_cullblade_grows_only_while_an_opponent_is_at_ten_or_less():
    engine = game()
    blade = card(engine, "Ruthless Cullblade")  # 2/1
    engine.state.player_by_id("p1").life = 10  # near miss: my own life
    engine.recompute_continuous_effects()
    assert (blade.power, blade.toughness) == (2, 1)
    engine.state.player_by_id("p2").life = 10
    engine.recompute_continuous_effects()
    assert (blade.power, blade.toughness) == (4, 2)


def test_lupine_prototype_attacks_only_while_some_player_has_an_empty_hand():
    engine = game()
    wolf = card(engine, "Lupine Prototype")
    p1, p2 = (engine.state.player_by_id(x) for x in ("p1", "p2"))
    card(engine, "Forest", zone=Zone.HAND)
    card(engine, "Forest", player="p2", zone=Zone.HAND)
    assert not engine._combat_restrictions_allow(wolf, "cant_attack_unless", p2)  # everyone holds a card
    p2.hand.clear()
    assert engine._combat_restrictions_allow(wolf, "cant_attack_unless", p2)  # "a player", not only me
    card(engine, "Forest", player="p2", zone=Zone.HAND)
    p1.hand.clear()
    assert engine._combat_restrictions_allow(wolf, "cant_attack_unless", p2)


def test_vampire_lacerator_upkeep_loss_is_skipped_when_an_opponent_is_at_ten_or_less():
    from tests.support.deck_batch import step

    engine = game()
    card(engine, "Vampire Lacerator")
    p1 = engine.state.player_by_id("p1")
    step(engine, "upkeep")
    assert p1.life == 19
    engine.state.player_by_id("p2").life = 10
    step(engine, "upkeep")
    assert p1.life == 19  # "unless an opponent has 10 or less life"


def test_opal_avenger_wakes_at_ten_life_via_a_state_trigger_not_before():
    engine = game()
    avenger = card(engine, "Opal Avenger")
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert not avenger.is_creature
    engine.state.player_by_id("p1").life = 10
    engine.rules.check_state_based_actions()
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert avenger.is_creature and (avenger.power, avenger.toughness) == (3, 5)


def _ultron_board():
    engine = game()
    card(engine, "Ultron, Unlimited")
    card(engine, "Ledger Shredder")
    engine.state.player_by_id("p1").mana_pool.add_many({"C": 3})
    _bolt_twice(engine)
    return engine


def test_ultron_pays_one_for_a_robot_when_a_creature_i_control_connives():
    engine = _ultron_board()
    assert engine.state.pending_choice["kind"] == "pay_cost_then"
    engine.resolve_pending_choice("pay")
    engine.resolve_until_stable()
    assert len(named(engine, "Robot Villain")) == 1


def test_ultron_declining_the_payment_makes_no_robot():
    engine = _ultron_board()
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert named(engine, "Robot Villain") == []


# --- play a land from exile or cast a spell from exile -----------------------------------------------------------


def _thopters(engine):
    return [o for o in engine.state.battlefield if o.name == "Thopter"]


def test_pia_nalaar_makes_a_thopter_for_exile_plays_not_for_hand_plays():
    engine = game()
    card(engine, "Pia Nalaar, Consul of Revival")
    p1 = engine.state.player_by_id("p1")
    _play_land(engine, "p1", "Forest")  # near miss: a land played from the hand
    assert _thopters(engine) == []
    cast(engine, card(engine, "Lightning Bolt", zone=Zone.HAND), targets=[engine.state.player_by_id("p2")])
    assert _thopters(engine) == []  # near miss: a spell cast from the hand
    # a land played from exile
    land = engine.rules.exile_with_play_permission(p1, 1)[0]
    p1.lands_played_this_turn = 0
    engine.state.active_player_index = 0
    main_phase(engine)
    engine.play_land(p1, land)
    engine.resolve_until_stable()
    assert len(_thopters(engine)) == 1
    # a spell cast from exile
    bolt = card(engine, "Lightning Bolt", zone=Zone.LIBRARY)
    stack_library(engine, "p1", bolt)
    exiled = engine.rules.exile_with_play_permission(p1, 1)
    assert exiled == [bolt]
    cast(engine, bolt, targets=[engine.state.player_by_id("p2")])
    assert len(_thopters(engine)) == 2


def test_guul_draz_vampire_gets_its_bonus_only_while_an_opponent_is_at_ten_or_less():
    engine = game()
    vampire = card(engine, "Guul Draz Vampire")  # 1/1
    base = (vampire.power, vampire.toughness)
    engine.state.player_by_id("p1").life = 10  # near miss: my own life
    engine.recompute_continuous_effects()
    assert (vampire.power, vampire.toughness) == base
    engine.state.player_by_id("p2").life = 10
    engine.recompute_continuous_effects()
    assert (vampire.power, vampire.toughness) == (base[0] + 2, base[1] + 1)
    assert "intimidate" in vampire.granted_keywords
    engine.state.player_by_id("p2").life = 11
    engine.recompute_continuous_effects()
    assert (vampire.power, vampire.toughness) == base and "intimidate" not in vampire.granted_keywords


def test_blood_baron_needs_thirty_life_for_me_and_ten_or_less_for_an_opponent():
    engine = game()
    baron = card(engine, "Blood Baron of Vizkopa")  # 3/3
    base = (baron.power, baron.toughness)
    p1, p2 = engine.state.player_by_id("p1"), engine.state.player_by_id("p2")
    p1.life, p2.life = 30, 10
    engine.recompute_continuous_effects()
    assert (baron.power, baron.toughness) == (base[0] + 6, base[1] + 6) and "flying" in baron.granted_keywords
    p1.life = 29  # near miss: one short of 30
    engine.recompute_continuous_effects()
    assert (baron.power, baron.toughness) == base and "flying" not in baron.granted_keywords
    p1.life, p2.life = 30, 11  # near miss: the opponent is above 10
    engine.recompute_continuous_effects()
    assert (baron.power, baron.toughness) == base

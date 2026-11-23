"""PAR-321: "that player" / "they" under player-event heads (land played, life lost, first spell each turn, each
player's / opponent's step) and "that many" over non-counter events (loyalty removed, group attack, combat damage,
life lost, a shuffle's size, a draw's count). Real cards on a real engine; every case has a bystander player or the
antecedent-did-not-happen path."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.deck_batch import answer, attack, card, cast, filler, game, named, step

NEWLY = ["Horn of Greed", "Mindcrank", "Pain Distributor", "Goblin Spymaster", "Crimson Honor Guard",
         "Furnace Punisher", "Cephalid Constable", "Chandra, Fire Artisan", "Earth Kingdom General",
         "Poetic Ingenuity", "Psychic Spiral", "Last Stand"]


@pytest.mark.parametrize("name", NEWLY)
def test_cards_are_modeled(name):
    assert parse_oracle(CardDatabase(DB_PATH).get_card(name)).coverage == MODELED


def _life(engine, pid):
    return engine.state.player_by_id(pid).life


def _hand(engine, pid):
    return len(engine.state.player_by_id(pid).hand)


def _set_active(engine, pid):
    engine.state.active_player_index = next(i for i, p in enumerate(engine.state.players) if p.id == pid)


# --- Horn of Greed: the player who played the land draws -----------------------------------------------------------------

@pytest.mark.parametrize("who,other", [("p1", "p2"), ("p2", "p1")])
def test_horn_of_greed_draws_for_the_player_who_played_the_land(who, other):
    engine = game()
    card(engine, "Horn of Greed")
    land = filler(engine, "Plains", type_line="Basic Land — Plains", player=who, zone=Zone.HAND)
    hands = {pid: _hand(engine, pid) for pid in ("p1", "p2")}
    engine.state.fire_event(GameEvent(EventType.LAND_PLAYED, player_id=who, card_id=land.card.id, land=land.name,
                                      instance_id=land.instance_id))
    engine.resolve_until_stable()
    assert _hand(engine, who) == hands[who] + 1
    assert _hand(engine, other) == hands[other]


# --- Mindcrank: the opponent who lost life mills that many ---------------------------------------------------------------

def test_mindcrank_mills_the_opponent_who_lost_life_by_the_life_lost_only():
    engine = game(players=3, library=12)
    card(engine, "Mindcrank")
    libs = {pid: len(engine.state.player_by_id(pid).library) for pid in ("p1", "p2", "p3")}
    engine.rules.lose_life(engine.state.player_by_id("p2"), 3)
    engine.resolve_until_stable()
    assert len(engine.state.player_by_id("p2").library) == libs["p2"] - 3
    assert len(engine.state.player_by_id("p3").library) == libs["p3"]    # a bystander opponent mills nothing
    engine.rules.lose_life(engine.state.player_by_id("p1"), 4)           # "an opponent": my own loss does nothing
    engine.resolve_until_stable()
    assert len(engine.state.player_by_id("p1").library) == libs["p1"]


# --- Pain Distributor: the caster's first spell each turn makes the caster a Treasure ------------------------------------

def test_pain_distributor_gives_the_caster_a_treasure_for_the_first_spell_only():
    engine = game()
    card(engine, "Pain Distributor")
    first = filler(engine, "Zap One", type_line="Instant", player="p2", zone=Zone.HAND)
    second = filler(engine, "Zap Two", type_line="Instant", player="p2", zone=Zone.HAND)
    cast(engine, first)
    assert len(named(engine, "Treasure", "p2")) == 1 and not named(engine, "Treasure", "p1")
    cast(engine, second)
    assert len(named(engine, "Treasure", "p2")) == 1                      # only the first spell each turn


# --- Goblin Spymaster / Crimson Honor Guard / Furnace Punisher: the step's player ---------------------------------------

def test_goblin_spymaster_makes_the_token_for_the_opponent_whose_end_step_it_is():
    engine = game()
    card(engine, "Goblin Spymaster")
    _set_active(engine, "p2")
    step(engine, "end", player="p2")
    assert len(named(engine, "Goblin", "p2")) == 1 and not named(engine, "Goblin", "p1")
    _set_active(engine, "p1")
    step(engine, "end", player="p1")                                      # "each opponent's": not my own end step
    assert not named(engine, "Goblin", "p1")


@pytest.mark.parametrize("commander_owner,damaged", [(None, True), ("p1", True), ("p2", False)])
def test_crimson_honor_guard_hurts_the_step_player_unless_that_player_controls_a_commander(commander_owner, damaged):
    engine = game()
    card(engine, "Crimson Honor Guard")
    if commander_owner is not None:
        cmdr = filler(engine, "Cmdr", power=1, toughness=1, player=commander_owner)
        cmdr.is_commander = True
    _set_active(engine, "p2")
    step(engine, "end", player="p2")
    assert (_life(engine, "p2") == 16) is damaged                         # 4 damage to the step's player
    assert _life(engine, "p1") == 20


@pytest.mark.parametrize("lands_owner,lands,damaged", [("p2", 2, False), ("p2", 1, True), ("p1", 2, True)])
def test_furnace_punisher_counts_the_step_players_basic_lands_not_mine(lands_owner, lands, damaged):
    engine = game()
    card(engine, "Furnace Punisher")
    for i in range(lands):
        filler(engine, f"Basic {i}", type_line="Basic Land — Forest", player=lands_owner)
    _set_active(engine, "p2")
    step(engine, "upkeep", player="p2")
    assert (_life(engine, "p2") == 18) is damaged
    assert _life(engine, "p1") == 20


# --- Chandra, Fire Artisan: damage equal to the loyalty removed ---------------------------------------------------------

def test_chandra_fire_artisan_deals_damage_equal_to_the_loyalty_counters_removed():
    engine = game()
    chandra = card(engine, "Chandra, Fire Artisan")
    engine.rules.add_counters(chandra, 5, "loyalty")
    engine.resolve_until_stable()
    answer(engine)
    before = _life(engine, "p2")
    engine.rules.add_counters(chandra, -3, "loyalty")
    engine.resolve_until_stable()
    answer(engine)
    assert _life(engine, "p2") == before - 3


# --- Earth Kingdom General: gain that much life, once each turn ---------------------------------------------------------

def test_earth_kingdom_general_gains_life_equal_to_the_counters_put_once_each_turn():
    engine = game()
    card(engine, "Earth Kingdom General")
    body = filler(engine, "Body", power=1, toughness=1)
    before = _life(engine, "p1")
    engine.rules.add_counters(body, 3, "+1/+1", source=body)
    engine.resolve_until_stable()
    answer(engine)
    assert _life(engine, "p1") == before + 3
    engine.rules.add_counters(body, 2, "+1/+1", source=body)
    engine.resolve_until_stable()
    answer(engine)
    assert _life(engine, "p1") == before + 3                              # "Do this only once each turn"


# --- Poetic Ingenuity: a Treasure for each attacking Dinosaur ---------------------------------------------------------

def test_poetic_ingenuity_makes_one_treasure_per_attacking_dinosaur_only():
    engine = game()
    card(engine, "Poetic Ingenuity")
    dinos = [filler(engine, f"Dino {i}", type_line="Creature — Dinosaur", power=2, toughness=2) for i in range(2)]
    other = filler(engine, "Bear", type_line="Creature — Bear", power=2, toughness=2)
    attack(engine, [*dinos, other])
    assert len(named(engine, "Treasure")) == 2


# --- Cephalid Constable: up to that many permanents, as many as the combat damage ------------------------------------

@pytest.mark.parametrize("damage", [1, 2, 3])
def test_cephalid_constable_offers_as_many_targets_as_the_combat_damage(damage):
    engine = game()
    constable = card(engine, "Cephalid Constable")
    theirs = [filler(engine, f"Perm {i}", power=1, toughness=1, player="p2") for i in range(4)]
    mine = filler(engine, "Mine", power=1, toughness=1)                   # "that player controls": never offered
    engine.rules.deal_damage(engine.state.player_by_id("p2"), damage, source=constable, combat=True)
    engine.resolve_until_stable()
    ids = {str(o.instance_id) for o in theirs}
    rounds = 0
    while engine.state.pending_choice is not None and rounds < 6:
        offered = {str(o["id"]) for o in engine.state.pending_choice["options"]}
        assert str(mine.instance_id) not in offered
        pick = next(i for i in sorted(offered & ids))
        ids.discard(pick)
        engine.rules.resolve_choice(pick)
        rounds += 1
    engine.resolve_until_stable()
    assert rounds == damage                                               # exactly "that many" picks were offered
    assert sum(o.zone != Zone.BATTLEFIELD for o in theirs) == damage and mine.zone == Zone.BATTLEFIELD


# --- Last Stand / Psychic Spiral: a spell's own count ------------------------------------------------------------------

def test_last_stand_draws_for_each_island_then_discards_that_many():
    engine = game()
    for i in range(2):
        filler(engine, f"Isle {i}", type_line="Basic Land — Island")
    victim = filler(engine, "Victim", power=1, toughness=1, player="p2")
    for i in range(5):
        filler(engine, f"Spare {i}", type_line="Instant", zone=Zone.HAND)
    library = len(engine.state.player_by_id("p1").library)
    cast(engine, card(engine, "Last Stand", zone=Zone.HAND), targets=[engine.state.player_by_id("p2"), victim])
    answer(engine, limit=8)
    assert len(engine.state.player_by_id("p1").library) == library - 2    # drew one card for each of the two Islands
    # ... and discarded that many: the spell itself plus the two discards
    assert len(engine.state.player_by_id("p1").graveyard) == 3


def test_psychic_spiral_mills_the_target_player_by_the_size_of_the_shuffled_graveyard():
    engine = game(library=12)
    for i in range(3):
        filler(engine, f"Gy {i}", type_line="Instant", zone=Zone.GRAVEYARD)
    mine = len(engine.state.player_by_id("p1").library)
    theirs = len(engine.state.player_by_id("p2").library)
    cast(engine, card(engine, "Psychic Spiral", zone=Zone.HAND), targets=[engine.state.player_by_id("p2")])
    assert len(engine.state.player_by_id("p2").library) == theirs - 3
    assert len(engine.state.player_by_id("p1").library) == mine + 3      # the three cards went into my library


# --- parse-level adversarial cases: what must stay unclaimed -------------------------------------------------------------

def _parse(text, **attrs):
    from types import SimpleNamespace
    fields = dict(name="Test Card", oracle_text=text, type_line="Artifact", keywords=[], mana_cost="", power=None,
                  toughness=None, card_faces=None, layout="normal", is_sorcery=False, is_instant=False)
    return parse_oracle(SimpleNamespace(**{**fields, **attrs}))


@pytest.mark.parametrize("text", [
    "Whenever you cast a spell, they draw a card.",                                # "they" names no other player
    "Whenever you play a land, that player draws a card.",                         # no player named by the head
    "Whenever a creature enters, return up to that many target permanents to their owners' hands.",  # no count
])
def test_event_player_shapes_without_a_named_player_stay_unclaimed(text):
    assert _parse(text).coverage != MODELED


def test_unless_they_control_is_asked_of_the_step_player_not_the_controller():
    result = _parse("At the beginning of each player's upkeep, ~ deals 2 damage to that player unless they control "
                    "a commander.")
    assert result.coverage == MODELED
    gate = result.specs[0].effects[0].condition
    assert gate["kind"] == "not" and gate["condition"]["kind"] == "as_active_player"


def test_group_attack_that_many_counts_only_the_filtered_attackers():
    result = _parse("Whenever one or more Dinosaurs you control attack, create that many Treasure tokens.")
    assert result.coverage == MODELED
    assert result.specs[0].trigger["attackers_declared"]["filter"] == {"subtype": "dinosaur"}
    assert "group_filter" not in result.specs[0].trigger["condition"]

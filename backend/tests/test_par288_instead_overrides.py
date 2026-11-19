"""PAR-288 (P1-F "instead"): "<do A>. If that <object> <state>, <do B> instead." (RULE 614.6 / 608.2c).

Real cards on a real engine. The gate reads the announced target when the instruction resolves; with the gate false
the printed base effect must run (and only it), and the replacement must replace -- never add to -- the base."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter.overrides_and_amounts import instead_override_specs
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.deck_batch import RICH, activate, answer, attack, card, cast, filler, game, main_phase

NEWLY = ["Bring Low", "Divine Smite", "Grey Knight Paragon", "Elder Cathar", "Purifying Dragon", "Sweep Away",
         "Erebos's Emissary", "Everflame Eidolon"]


@pytest.mark.parametrize("name", NEWLY)
def test_cards_are_modeled(name):
    assert parse_oracle(CardDatabase(DB_PATH).get_card(name)).coverage == MODELED


def test_parse_shapes_keep_the_targets_own_qualifiers():
    (spec,) = instead_override_specs(
        "put a +1/+1 counter on target creature you control. if that creature is a human, "
        "put 2 +1/+1 counters on it instead.")
    for branch in ("then", "else"):
        assert spec.params[branch][0]["params"]["target_kind"] == "creature_you_control"
    (dragon,) = instead_override_specs(
        "~ deals 1 damage to target creature defending player controls. if that creature is a zombie, "
        "~ deals 2 damage to it instead.")
    assert dragon.type == "bind"                                  # one hit whose size the gate picks (RULE 614.6)
    assert dragon.params["amount"]["then"] == 2 and dragon.params["amount"]["otherwise"] == 1
    assert dragon.params["effects"][0]["params"]["target_kind"] == "creature_defending_player_controls"


def test_a_gate_on_one_of_two_announced_targets_is_not_claimed():
    # two announced targets leave "that creature" without one referent (RULE 608.2c).
    assert instead_override_specs(
        "destroy target creature and target land. if that creature is a demon, exile it instead.") is None


def _marked(obj):
    return obj.damage_marked


# --- Bring Low ----------------------------------------------------------------------------------------------------

def test_bring_low_deals_five_to_a_creature_with_a_counter_and_three_to_one_without():
    engine = game()
    countered = filler(engine, "Countered", power=1, toughness=9, player="p2")
    plain = filler(engine, "Plain", power=1, toughness=9, player="p2")
    engine.rules.add_counters(countered, 1, "+1/+1")
    engine.rules.add_counters(plain, 1, "-1/-1")                   # a different kind of counter does not count
    cast(engine, card(engine, "Bring Low", zone=Zone.HAND), targets=[countered])
    cast(engine, card(engine, "Bring Low", zone=Zone.HAND), targets=[plain])
    assert _marked(countered) == 5 and _marked(plain) == 3         # replaced, not 3 + 5


# --- Divine Smite --------------------------------------------------------------------------------------------------

def test_divine_smite_exiles_a_black_permanent_and_only_phases_out_another_colour():
    engine = game()
    black = filler(engine, "Black", mana_cost_string="{B}", mv=1, power=2, toughness=2, player="p2")
    white = filler(engine, "White", mana_cost_string="{W}", mv=1, power=2, toughness=2, player="p2")
    cast(engine, card(engine, "Divine Smite", zone=Zone.HAND), targets=[black])
    cast(engine, card(engine, "Divine Smite", zone=Zone.HAND), targets=[white])
    assert black.zone == Zone.EXILE
    assert white.zone == Zone.BATTLEFIELD and white.phased_out     # the base effect, not the replacement


# --- Grey Knight Paragon -------------------------------------------------------------------------------------------

def _paragon_etb(engine, victim):
    from tests.support.deck_batch import put_on_battlefield
    victim.attacking = True
    put_on_battlefield(engine, "Grey Knight Paragon")
    answer(engine, pick=lambda c: next((str(o["id"]) for o in c["options"] if str(o["id"]) == str(victim.instance_id)), None))
    engine.resolve_until_stable()


def test_grey_knight_paragon_exiles_a_demon_but_destroys_any_other_attacker():
    engine = game()
    demon = filler(engine, "Imp", type_line="Creature — Demon", power=2, toughness=2, player="p2")
    other = filler(engine, "Goblin", type_line="Creature — Goblin", power=2, toughness=2, player="p2")
    _paragon_etb(engine, demon)
    assert demon.zone == Zone.EXILE
    engine2 = game()
    other = filler(engine2, "Goblin", type_line="Creature — Goblin", power=2, toughness=2, player="p2")
    _paragon_etb(engine2, other)
    assert other.zone == Zone.GRAVEYARD


# --- Elder Cathar --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("type_line,expected", [("Creature — Human", 2), ("Creature — Elf", 1)])
def test_elder_cathar_puts_two_counters_on_a_human_and_one_on_anything_else(type_line, expected):
    engine = game()
    cathar = card(engine, "Elder Cathar")
    friend = filler(engine, "Friend", type_line=type_line, power=1, toughness=1)
    bystander = filler(engine, "Bystander", type_line="Creature — Human", power=1, toughness=1)
    engine.rules.destroy(cathar)
    engine.resolve_until_stable()
    answer(engine, pick=lambda c: next((str(o["id"]) for o in c["options"] if str(o["id"]) == str(friend.instance_id)), None))
    engine.resolve_until_stable()
    assert friend.counters.get("+1/+1", 0) == expected
    assert bystander.counters.get("+1/+1", 0) == 0


# --- Purifying Dragon ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("type_line,expected", [("Creature — Zombie", 2), ("Creature — Elf", 1)])
def test_purifying_dragon_deals_two_to_a_zombie_and_one_to_anything_else(type_line, expected):
    engine = game()
    dragon = card(engine, "Purifying Dragon")
    victim = filler(engine, "Victim", type_line=type_line, power=1, toughness=9, player="p2")
    bystander = filler(engine, "Bystander", type_line="Creature — Zombie", power=1, toughness=9, player="p2")
    attack(engine, [dragon])
    answer(engine, pick=lambda c: next((str(o["id"]) for o in c["options"] if str(o["id"]) == str(victim.instance_id)), None))
    engine.resolve_until_stable()
    assert _marked(victim) == expected and _marked(bystander) == 0


# --- Sweep Away ----------------------------------------------------------------------------------------------------

def test_sweep_away_bounces_a_non_attacker_whatever_the_player_wants():
    engine = game()
    victim = filler(engine, "Victim", power=1, toughness=1, player="p2")
    cast(engine, card(engine, "Sweep Away", zone=Zone.HAND), targets=[victim])
    assert engine.state.pending_choice is None                     # the gate is false: no optional replacement offered
    assert victim.zone == Zone.HAND


@pytest.mark.parametrize("answer_id,zone", [("yes", Zone.LIBRARY), ("decline", Zone.HAND)])
def test_sweep_away_lets_the_player_put_an_attacker_on_the_library_or_decline_and_bounce_it(answer_id, zone):
    engine = game()
    victim = filler(engine, "Victim", power=1, toughness=1, player="p2")
    victim.attacking = True
    cast(engine, card(engine, "Sweep Away", zone=Zone.HAND), targets=[victim])
    choice = engine.state.pending_choice
    assert choice is not None and choice["kind"] == "composite_optional"   # "you may": the player decides
    engine.resolve_pending_choice(answer_id)
    engine.resolve_until_stable()
    assert victim.zone == zone                                     # declined: the printed bounce still happens
    assert victim in (engine.state.player_by_id("p2").library if zone == Zone.LIBRARY
                      else engine.state.player_by_id("p2").hand)


# --- Erebos's Emissary / Everflame Eidolon ----------------------------------------------------------------------------

def test_everflame_eidolon_pumps_itself_when_it_is_a_creature():
    engine = game()
    eidolon = card(engine, "Everflame Eidolon")
    engine.state.player_by_id("p1").mana_pool.add_many({"R": 1})
    host = filler(engine, "Host", power=1, toughness=1)
    base = eidolon.power
    activate(engine, eidolon, index=0)
    assert eidolon.power == base + 1 and host.power == 1


def test_everflame_eidolon_pumps_the_enchanted_creature_when_it_is_an_aura():
    engine = game()
    main_phase(engine)
    eidolon = card(engine, "Everflame Eidolon", zone=Zone.HAND)
    host = filler(engine, "Host", power=1, toughness=1)
    p1 = engine.state.player_by_id("p1")
    p1.mana_pool.add_many({"R": 3})
    engine.cast_spell(p1, eidolon, [host], face="bestow")
    engine.resolve_until_stable()
    assert eidolon.bestowed and eidolon.attached_to == host.instance_id
    before = host.power
    p1.mana_pool.add_many({"R": 1})
    engine.activate_ability(p1, eidolon, 0)
    engine.resolve_until_stable()
    assert host.power == before + 1                                # the host, on top of the Aura's own +1/+1 anthem


def test_erebos_emissary_follows_the_same_aura_gate():
    engine = game()
    main_phase(engine)
    emissary = card(engine, "Erebos's Emissary", zone=Zone.HAND)
    host = filler(engine, "Host", power=1, toughness=1)
    p1 = engine.state.player_by_id("p1")
    p1.mana_pool.add_many({"B": 6})
    engine.cast_spell(p1, emissary, [host], face="bestow")
    engine.resolve_until_stable()
    fodder = filler(engine, "Fodder", power=1, toughness=1, zone=Zone.HAND)
    before = host.power
    engine.activate_ability(p1, emissary, 0)
    engine.resolve_until_stable()
    assert host.power == before + 2 and fodder.zone == Zone.GRAVEYARD


# --- Will of the All-Hunter: a bare "it" is the announced target, not the resolving spell ---------------------------------

def test_will_of_the_all_hunter_reads_blocking_on_the_target_creature():
    from mtg_analyzer.parser.oracle.gate import parse_oracle as parse
    (spec,) = [s for s in parse(CardDatabase(DB_PATH).get_card("Will of the All-Hunter")).specs if s.effects]
    assert spec.effects[0].condition is None and spec.effects[0].type == "if_else"
    assert spec.effects[0].params["condition"]["of"] == "target"


def test_will_of_the_all_hunter_puts_counters_on_a_blocker_and_pumps_a_non_blocker():
    engine = game()
    blocker = filler(engine, "Blocker", power=1, toughness=1)
    idle = filler(engine, "Idle", power=1, toughness=1)
    attacker = filler(engine, "Attacker", power=1, toughness=1, player="p2")
    blocker.blocking = attacker.instance_id
    cast(engine, card(engine, "Will of the All-Hunter", zone=Zone.HAND), targets=[blocker])
    cast(engine, card(engine, "Will of the All-Hunter", zone=Zone.HAND), targets=[idle])
    assert blocker.counters.get("+1/+1", 0) == 2                    # "instead": counters, and no +2/+2 on top
    assert blocker.power == 3
    assert idle.counters.get("+1/+1", 0) == 0 and idle.power == 3   # the base pump (+2/+2) on a creature not blocking


# --- Flare of Faith: an already-MODELED spec whose gate was rescoped from the spell to the target ----------------------

@pytest.mark.parametrize("type_line,power,indestructible", [("Creature — Human", 4, True), ("Creature — Elf", 3, False)])
def test_flare_of_faith_gives_a_human_the_bigger_pump_and_indestructible_instead(type_line, power, indestructible):
    from mtg_analyzer.game import combat
    engine = game()
    victim = filler(engine, "Victim", type_line=type_line, power=1, toughness=1)
    bystander = filler(engine, "Bystander", type_line="Creature — Human", power=1, toughness=1)
    cast(engine, card(engine, "Flare of Faith", zone=Zone.HAND), targets=[victim])
    engine.recompute_continuous_effects()
    assert victim.power == power and victim.toughness == power         # +3/+3 replaces +2/+2 (never stacks)
    assert ("indestructible" in combat._obj_keywords(victim)) is indestructible
    assert bystander.power == 1                                         # a same-type bystander is untouched


def test_burning_hands_deals_six_to_a_green_permanent_and_two_to_any_other_colour():
    engine = game()
    green = filler(engine, "Green", mana_cost_string="{G}", mv=1, power=1, toughness=9, player="p2")
    red = filler(engine, "Red", mana_cost_string="{R}", mv=1, power=1, toughness=9, player="p2")
    cast(engine, card(engine, "Burning Hands", zone=Zone.HAND), targets=[green])
    cast(engine, card(engine, "Burning Hands", zone=Zone.HAND), targets=[red])
    assert _marked(green) == 6 and _marked(red) == 2

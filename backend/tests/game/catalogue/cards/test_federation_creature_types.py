"""MEC-143: the Federation ability word's "number of creature types among non-Borg creatures you control".

Real cached cards on a real engine. Rules: RULE 205.3m (creature types), RULE 702.73a (Changeling is every creature
type), RULE 613 (layer-4 type changes), RULE 608.2h (the amount is measured once on resolution).
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.creature_type_counts import CREATURE_TYPES_AMONG_NON_BORG_CREATURES_YOU_CONTROL as SELECTOR
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.cards.creature_types import CREATURE_SUBTYPES
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.card_cache import get_cached_card
from tests.support.star_trek import advance_to, attack, cast, game, on_battlefield, stock_library

#: The creatures in these tests are 1/1s so combat and pump arithmetic stays obvious.
BODY = 1
#: Survives any damage these tests deal, so the marked damage can be read back.
BIG_TOUGHNESS = 20


def creature(engine, player_id, type_line, name=None, *, token=False, toughness=BODY):
    """A plain creature with ``type_line`` already on ``player_id``'s battlefield (a token when ``token``)."""
    name = name or f"Test {type_line}"
    obj = GameObject(
        Card(id=name.replace(" ", ""), name=name, type_line=f"Creature — {type_line}", is_creature=True,
             power=BODY, toughness=toughness),
        owner_id=player_id, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = player_id
    obj.summoning_sick = False
    obj.is_token = token
    engine.state.add_to_battlefield(obj)
    engine.recompute_continuous_effects()
    return obj


def count(engine, player_id="p1"):
    engine.recompute_continuous_effects()
    return continuous.count_selector(engine.state, player_id, SELECTOR)


def test_each_type_counts_once_however_many_creatures_share_it():
    engine, _p1, _p2 = game()
    creature(engine, "p1", "Human Soldier", "A")
    creature(engine, "p1", "Human Wizard", "B")
    assert count(engine) == 3  # Human, Soldier, Wizard


def test_only_your_own_creatures_count():
    engine, _p1, _p2 = game()
    creature(engine, "p1", "Elf")
    creature(engine, "p2", "Goblin Warrior", "Theirs")
    assert count(engine) == 1 and count(engine, "p2") == 2


def test_non_creature_permanents_and_land_types_are_ignored():
    engine, _p1, _p2 = game()
    creature(engine, "p1", "Elf")
    on_battlefield(engine, "p1", "Forest")  # a land type is not a creature type (RULE 205.3i vs 205.3m)
    assert count(engine) == 1


def test_a_borg_contributes_nothing_even_for_types_it_shares():
    engine, _p1, _p2 = game()
    creature(engine, "p1", "Human Soldier", "Plain")
    creature(engine, "p1", "Borg Human Wizard", "Assimilated")
    # The Borg's Wizard is not counted, and its Human is counted only through the non-Borg creature.
    assert count(engine) == 2  # Human, Soldier


def test_a_type_only_a_borg_has_is_not_counted():
    engine, _p1, _p2 = game()
    creature(engine, "p1", "Borg Drone", "Only Borg")
    assert count(engine) == 0


def test_changeling_is_a_borg_so_it_contributes_nothing():
    # RULE 702.73a: a changeling has every creature type, Borg included; it is excluded like any other Borg.
    engine, _p1, _p2 = game()
    on_battlefield(engine, "p1", "Changeling Outcast")
    creature(engine, "p1", "Elf")
    assert count(engine) == 1


def test_a_creature_granted_every_creature_type_becomes_a_borg_and_drops_out():
    # Maskwood Nexus: "Creatures you control are every creature type" (RULE 702.73a-style grant through layer 4).
    engine, _p1, _p2 = game()
    elf = creature(engine, "p1", "Elf")
    assert count(engine) == 1
    on_battlefield(engine, "p1", "Maskwood Nexus")
    assert "borg" in continuous.creature_types_of(elf)
    assert count(engine) == 0


def test_a_token_counts_by_its_types():
    engine, _p1, _p2 = game()
    creature(engine, "p1", "Elf Druid", "Token", token=True)
    assert count(engine) == 2


def test_a_creature_that_loses_its_types_stops_counting_them():
    # Darksteel Mutation (layer 4): enchanted creature is an Insect and loses all other creature types.
    engine, p1, _p2 = game("Darksteel Mutation")
    elf = creature(engine, "p1", "Elf Druid")
    creature(engine, "p1", "Elf Wizard", "Other")
    assert count(engine) == 3
    mutation = p1.hand[0]
    cast(engine, p1, mutation, targets=[elf])
    assert continuous.creature_types_of(elf) == {"insect"}
    assert count(engine) == 3  # Elf (via the Wizard), Wizard, Insect; Druid is gone
    assert "druid" not in continuous.creature_types_of(elf)


def test_borg_is_a_known_creature_type():
    assert "borg" in CREATURE_SUBTYPES


# --- the seven Federation cards ------------------------------------------------------------------------------------

def _board(engine):
    """Three distinct creature types on p1's side (Elf, Druid, Wizard)."""
    creature(engine, "p1", "Elf Druid", "A")
    creature(engine, "p1", "Elf Wizard", "B")


def test_captain_archer_pumps_by_the_type_count_at_sorcery_speed():
    engine, p1, _p2 = game()
    archer = on_battlefield(engine, "p1", "Captain Jonathan Archer")  # Human Officer: 2 types
    _board(engine)                                                     # + Elf, Druid, Wizard
    target = creature(engine, "p1", "Bear", "Target")                  # + Bear
    archer.summoning_sick = False
    p1.mana_pool.add_many({"G": 1})
    engine.activate_ability(p1, archer, targets=[target])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert count(engine) == 6
    assert target.power == BODY + 6 and target.toughness == BODY + 6


def test_hoshi_sato_looks_at_that_many_cards_and_takes_one():
    engine, p1, _p2 = game("Hoshi Sato, Exolinguist")
    _board(engine)  # Elf, Druid, Wizard; Hoshi (a Human Advisor-style body) adds her own types once on the battlefield
    library = stock_library(engine, "p1", 10)
    hoshi = p1.hand[0]
    cast(engine, p1, hoshi)
    types = count(engine)
    assert types >= 4
    choice = engine.state.pending_choice
    assert choice is not None and choice["kind"] == "look_top_select"
    offered = [o for o in choice["options"] if o.get("instance_id") is not None]
    assert len(offered) == types  # looked at exactly X cards
    taken = offered[0]
    engine.resolve_pending_choice(taken["id"])
    for _ in range(types):  # the rest go to the bottom in a random order (no further prompt expected)
        if engine.state.pending_choice is None:
            break
        engine.resolve_pending_choice(engine.state.pending_choice["options"][0]["id"])
    engine.resolve_until_stable()
    assert any(o.instance_id == taken["instance_id"] for o in p1.hand)
    assert len(p1.library) == len(library) - 1


def test_saavik_deals_the_type_count_to_an_attacking_creature_an_opponent_controls():
    engine, p1, _p2 = game("Saavik, Stoic Student")
    _board(engine)  # Elf, Druid, Wizard
    victim = creature(engine, "p2", "Giant", "Victim", toughness=BIG_TOUGHNESS)
    victim.attacking = True  # RULE 506.4: an attacking creature (the target's legality, not combat itself, is tested)
    saavik = p1.hand[0]
    cast(engine, p1, saavik)
    choice = engine.state.pending_choice
    assert choice["kind"] == "trigger_target" and [o["instance_id"] for o in choice["options"]] == [victim.instance_id]
    engine.resolve_pending_choice(choice["options"][0]["id"])
    engine.resolve_until_stable()
    types = count(engine)
    assert types >= 4  # Elf, Druid, Wizard + Saavik's own Vulcan Advisor
    assert victim.damage_marked == types


def test_starfleet_academy_adds_that_much_mana_of_a_chosen_color():
    from mtg_analyzer.game.mana_abilities import mana_abilities_for, parse_mana_abilities, resolve_options

    engine, p1, _p2 = game()
    academy = on_battlefield(engine, "p1", "Starfleet Academy")
    _board(engine)
    abilities = [a for a in parse_mana_abilities(academy.card) if a.amount_selector is not None]
    assert len(abilities) == 1
    options = resolve_options(abilities[0], academy, engine.state)
    assert sorted(options, key=lambda o: sorted(o)) == sorted(({c: 3} for c in "WUBRG"), key=lambda o: sorted(o))


def test_starfleet_academy_taps_for_that_much_mana_through_the_engine():
    engine, p1, _p2 = game()
    academy = on_battlefield(engine, "p1", "Starfleet Academy")
    _board(engine)
    p1.mana_pool.add_many({"C": 5})
    # Ability 0 is the plain {T}: Add {C}; ability 1 is the Federation one ({5}, {T}), with the colour menu as options.
    engine.tap_for_mana(p1, academy, option_index=3, ability_index=1)  # option 3 of W, U, B, R, G is R
    assert p1.mana_pool.total() == 3  # the {5} was paid out of the pool; three red mana (one per creature type) added
    assert academy.tapped


def _begin_combat(engine):
    from mtg_analyzer.models.game.events import EventType, GameEvent

    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="begin_combat", player_id="p1", controller_id="p1"))
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()


def test_sarek_draws_one_card_per_five_types_and_adds_counters_at_fifteen():
    engine, p1, _p2 = game()
    on_battlefield(engine, "p1", "Sarek, Federation Ambassador")  # Vulcan, Advisor
    stock_library(engine, "p1", 10)
    for i, types in enumerate(("Elf Druid Wizard", "Goblin Warrior Shaman")):
        creature(engine, "p1", types, f"G{i}")
    assert count(engine) == 8  # 2 + 6
    before = len(p1.hand)
    _begin_combat(engine)
    assert len(p1.hand) == before + 1  # 8 // 5
    assert all(o.counters.get("+1/+1", 0) == 0 for o in engine.state.battlefield)  # drew fewer than three


def test_sarek_puts_two_counters_on_each_creature_when_it_draws_three_or_more():
    engine, p1, _p2 = game()
    sarek = on_battlefield(engine, "p1", "Sarek, Federation Ambassador")
    stock_library(engine, "p1", 10)
    pool = sorted(CREATURE_SUBTYPES - {"borg", "vulcan", "advisor"} - {t for t in CREATURE_SUBTYPES if " " in t})
    # 13 plain types on one creature, plus Sarek's Vulcan and Advisor: exactly 15 types, so three cards.
    wide = creature(engine, "p1", " ".join(t.title() for t in pool[:13]), "Wide")
    assert count(engine) == 15
    before = len(p1.hand)
    _begin_combat(engine)
    assert len(p1.hand) == before + 3
    assert sarek.counters.get("+1/+1") == 2 and wide.counters.get("+1/+1") == 2


def test_jean_luc_gives_faeries_a_counter_per_creature_type_already_controlled():
    engine, p1, _p2 = game("Faerie Seer")
    on_battlefield(engine, "p1", "Jean-Luc, Mon Capitaine")  # Human Officer
    creature(engine, "p1", "Elf Druid", "A")
    creature(engine, "p1", "Borg Wizard", "BorgOnly")  # the Borg contributes nothing
    assert count(engine) == 4  # Human, Officer, Elf, Druid
    faerie = p1.hand[0]
    cast(engine, p1, faerie)
    assert faerie.zone == Zone.BATTLEFIELD
    assert faerie.counters.get("+1/+1") == 4  # counted before the Faerie (and its own types) entered


def test_jean_luc_does_not_boost_other_creature_types():
    engine, p1, _p2 = game("Grizzly Bears")
    on_battlefield(engine, "p1", "Jean-Luc, Mon Capitaine")
    bears = p1.hand[0]
    cast(engine, p1, bears)
    assert bears.counters.get("+1/+1", 0) == 0


def test_infinite_diversity_copies_the_exiled_spell_x_times_and_exiles_itself():
    engine, p1, p2 = game("Infinite Diversity")
    creature(engine, "p1", "Elf Druid", "A")  # Elf, Druid: X = 2
    bolt = GameObject(get_cached_card("Lightning Bolt"), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(bolt)
    life = p2.life
    spell = p1.hand[0]
    cast(engine, p1, spell, targets=[bolt])
    choice = engine.state.pending_choice
    assert choice is not None and choice["kind"] == "play_during_resolution"
    assert len(choice["instance_ids"]) == 2  # X copies, offered together
    first = engine.state.find_object(choice["instance_ids"][0])
    engine.play_resolution_card(p1, first, targets=[p2])  # cast one copy free (RULE 707.12 / 608.2g)
    engine.resolve_until_stable()
    remaining = engine.state.pending_choice
    assert remaining is not None and remaining["kind"] == "play_during_resolution"  # the second copy is still offered
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert p2.life == life - 3  # exactly one Lightning Bolt resolved
    assert spell in p1.exile and spell not in p1.graveyard  # "Exile Infinite Diversity"
    assert not [o for o in p1.exile if getattr(o, "is_copy", False)]  # the declined copy ceased to exist (RULE 707.10a)


def test_infinite_diversity_with_no_types_makes_no_copies():
    engine, p1, _p2 = game("Infinite Diversity")
    bolt = GameObject(get_cached_card("Lightning Bolt"), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(bolt)
    spell = p1.hand[0]
    cast(engine, p1, spell, targets=[bolt])
    assert engine.state.pending_choice is None
    assert spell in p1.exile


def test_three_tree_city_counted_mana_uses_the_chosen_type():
    """The counted chosen-colour mana rule also reads Three Tree City's "creatures you control of the chosen type"."""
    from mtg_analyzer.game.mana_abilities import parse_mana_abilities, resolve_options

    engine, _p1, _p2 = game()
    city = on_battlefield(engine, "p1", "Three Tree City")
    city.chosen_type = "Elf"
    creature(engine, "p1", "Elf Druid", "A")
    creature(engine, "p1", "Elf Wizard", "B")
    creature(engine, "p1", "Goblin", "C")
    ability = next(a for a in parse_mana_abilities(city.card) if a.amount_selector is not None)
    options = resolve_options(ability, city, engine.state)
    assert {tuple(o.values()) for o in options} == {(2,)}

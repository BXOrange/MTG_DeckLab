"""PAR-270: disjunctive creature-type lists ("Klingons and Warriors you control").

RULE 205.3m: a list of creature types is a union (an object with *any* listed type), unlike a multi-word phrase
("Elf Warrior creatures"), which is an intersection. Parse checks use synthetic cards; behaviour checks run the real
cached Star Trek cards on a real engine.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from tests.support.star_trek import cast, game, on_battlefield, vanilla


def _parse(text: str, *, sorcery: bool = False):
    if sorcery:
        card = Card(id="t", name="Foo Bar", type_line="Sorcery", oracle_text=text, is_sorcery=True)
    else:
        card = Card(id="t", name="Foo Bar", type_line="Creature — Human", oracle_text=text, is_creature=True,
                    power=1, toughness=1)
    return parse_oracle(card)


def _effects(result) -> list:
    return [e for spec in result.specs for e in spec.effects]


def _tribal(engine, owner: str, name: str, type_line: str, power: int = 2, toughness: int = 2) -> GameObject:
    """A plain battlefield creature with the given type line."""
    obj = vanilla(engine, owner, name, power, toughness)
    obj.card.type_line = type_line
    engine.recompute_continuous_effects()
    return obj


# ---- parse ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("text, subtypes", [
    ("Klingons and Warriors you control have vigilance.", ["Klingon", "Warrior"]),
    ("Skeletons, Vampires, and Zombies you control get +1/+1.", ["Skeleton", "Vampire", "Zombie"]),
    ("Klingons and/or Warriors you control get +1/+1.", ["Klingon", "Warrior"]),
])
def test_bare_plural_type_list_is_a_subtype_union(text, subtypes):
    result = _parse(text)
    assert result.coverage == MODELED
    (effect,) = _effects(result)
    assert effect.params["object_filter"] == {"subtype_any": subtypes}
    assert "subtype" not in effect.params


def test_attacking_qualifier_covers_every_listed_type():
    (effect,) = _effects(_parse("Attacking Ninjas and Rogues you control have deathtouch."))
    assert effect.params["affects"] == "attacking_creatures_you_control"
    assert effect.params["object_filter"] == {"subtype_any": ["Ninja", "Rogue"]}


def test_trailing_creatures_noun_list_with_commas_and_other():
    (effect,) = _effects(_parse("Other Officers, Artificers, and Spacecraft creatures you control get +2/+2."))
    assert effect.params["affects"] == "other_creatures_you_control"
    assert [alt["subtype"] for alt in effect.params["object_filter"]["any_of"]] == ["Officer", "Artificer", "Spacecraft"]


def test_a_two_word_type_phrase_stays_an_intersection():
    (effect,) = _effects(_parse("Elf Warrior creatures you control get +1/+1."))
    assert "subtype_any" not in effect.params.get("object_filter", {})
    assert "any_of" not in effect.params.get("object_filter", {})


@pytest.mark.parametrize("text", [
    "Artifacts and lands you control have indestructible.",
    "Creatures and enchantments you control have hexproof.",
])
def test_a_card_type_list_is_never_read_as_a_tribe(text):
    result = _parse(text)
    assert all(
        "subtype_any" not in (e.params.get("object_filter") or {}) and "subtype" not in e.params
        for e in _effects(result)
    )


def test_a_comma_in_a_conditional_prefix_is_not_a_type_list():
    # Goblin Caves / Path of Bravery: the comma ends an "as long as" condition, it does not separate creature types.
    for text in (
        "As long as enchanted land is a basic Mountain, Goblin creatures get +0/+2.",
        "As long as your life total is greater than or equal to your starting life total, creatures you control get +1/+1.",
    ):
        assert not any("any_of" in str(e.params) for e in _effects(_parse(text))), text


def test_a_non_creature_type_in_a_bare_list_fails_closed():
    # "Treefolk and Forests you control" is not a set of creatures; neither is "Mounts and Vehicles".
    for text in ("Treefolk and Forests you control have indestructible.", "Mounts and Vehicles you control have hexproof."):
        assert _parse(text).coverage != MODELED, text


def test_group_pump_accepts_an_attacking_union_and_comma_lists():
    for text in (
        "Whenever Foo Bar attacks, attacking Klingons and Warriors you control get +1/+1 until end of turn.",
        "Whenever Foo Bar attacks, Elves, Goblins, and Orcs you control get +1/+1 until end of turn.",
    ):
        result = _parse(text)
        assert result.coverage == MODELED, text
        assert "subtype_any" in _effects(result)[0].params["selector"]["filter"]


@pytest.mark.parametrize("text", [
    "Klingon spells and Warrior spells you cast cost {1} less to cast.",
    "Klingon and Warrior spells you cast cost {1} less to cast.",
])
def test_cost_reduction_over_a_type_union(text):
    (effect,) = _effects(_parse(text))
    assert effect.type == "cost_reduction"
    assert effect.params["spell_subtype"] == ["klingon", "warrior"] and effect.params["generic"] == 1


def test_main_type_spell_pairs_keep_their_old_reading():
    (effect,) = _effects(_parse("Instant and sorcery spells you cast cost {1} less to cast."))
    assert effect.params["spell_type"] == ["instant", "sorcery"] and "spell_subtype" not in effect.params


def test_range_target_over_a_type_union():
    result = _parse("When Foo Bar enters, one or two target Klingons and/or Warriors you control gain flying until end of turn.")
    assert result.coverage == MODELED
    announce = _effects(result)[0].params["effects"][0]["params"]
    assert (announce["count"], announce["count_max"], announce["optional"]) == (1, 2, False)
    assert announce["creature_filter"] == {"subtype_any": ["klingon", "warrior"]}


def test_up_to_still_means_optional_and_has_no_range():
    result = _parse("When Foo Bar enters, up to two target Elves you control gain flying until end of turn.")
    announce = _effects(result)[0].params["effects"][0]["params"]
    assert announce["optional"] is True and "count_max" not in announce


def test_graveyard_return_over_a_type_union_excludes_the_sacrificed_card():
    result = _parse(
        "You may sacrifice a Klingon or Warrior. If you do, return all other Klingon and Warrior creature cards "
        "from your graveyard to the battlefield.", sorcery=True,
    )
    assert result.coverage == MODELED
    inner = _effects(result)[0].params["effects"][0]["params"]
    assert inner["subtype_any"] == ["klingon", "warrior"] and inner["exclude_sacrificed"] is True


def test_graveyard_return_rejects_a_non_subtype_word():
    assert _parse("Return all damaged cards from your graveyard to the battlefield.", sorcery=True).coverage != MODELED


def test_all_six_ticket_cards_are_modeled():
    from tests.support.card_cache import get_cached_card

    for name in ("Gagh Slinger", "I.K.S. Negh'Var, Imperial Flagship", "K't'inga-Class Battle Cruiser",
                 "Kirk, Man of Action", "Kruge, Genesis Seeker", "The Promise of Kahless"):
        card = get_cached_card(name)
        assert card is not None, name
        assert parse_oracle(card).coverage == MODELED, name


# ---- real engine ---------------------------------------------------------------------------------------------------


def test_negh_var_grants_vigilance_to_klingons_and_to_warriors_but_not_others():
    engine, p1, p2 = game()
    on_battlefield(engine, "p1", "I.K.S. Negh'Var, Imperial Flagship")
    klingon = _tribal(engine, "p1", "K", "Creature — Klingon")
    warrior = _tribal(engine, "p1", "W", "Creature — Human Warrior")
    bear = _tribal(engine, "p1", "B", "Creature — Bear")
    theirs = _tribal(engine, "p2", "T", "Creature — Klingon")
    assert combat.has(klingon, "vigilance") and combat.has(warrior, "vigilance")
    assert not combat.has(bear, "vigilance") and not combat.has(theirs, "vigilance")


def test_kirk_pumps_each_listed_type_but_not_himself_or_others():
    engine, p1, p2 = game()
    kirk = on_battlefield(engine, "p1", "Kirk, Man of Action")
    officer = _tribal(engine, "p1", "O", "Creature — Human Officer")
    scientist = _tribal(engine, "p1", "S", "Creature — Vulcan Scientist")
    craft = _tribal(engine, "p1", "C", "Artifact Creature — Spacecraft")
    bear = _tribal(engine, "p1", "B", "Creature — Bear")
    assert (officer.power, scientist.power, craft.power) == (4, 4, 4)
    assert bear.power == 2
    assert kirk.power == kirk.card.power  # "other"


def test_kruge_pumps_only_attacking_klingons():
    engine, p1, p2 = game(via_steps=True)
    kruge = on_battlefield(engine, "p1", "Kruge, Genesis Seeker")
    klingon = _tribal(engine, "p1", "K", "Creature — Klingon")
    idle_klingon = _tribal(engine, "p1", "IK", "Creature — Klingon")
    warrior = _tribal(engine, "p1", "W", "Creature — Human Warrior")
    attack_started = (kruge.power, klingon.power)
    # Declare Kruge, one Klingon and the Warrior; stop right after the trigger resolved (before damage).
    while engine.state.current_step != "declare_attackers":
        engine.advance_step()
    defender = engine.legal_defenders_for(p1)[0]
    for obj in (kruge, klingon, warrior):
        obj.summoning_sick = False
    engine.declare_attackers(p1, [{"attacker": a, "defender": defender} for a in (kruge, klingon, warrior)])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert kruge.power == attack_started[0] + 1 and klingon.power == attack_started[1] + 1
    assert idle_klingon.power == 2 and warrior.power == 2  # not a Klingon / not attacking


def _cost_paid_for(engine, player, card_obj, pool: dict) -> bool:
    """Whether ``card_obj`` can be cast from exactly ``pool`` (so a discount shows as a cheaper cast)."""
    player.mana_pool.add_many(pool)
    try:
        engine.cast_spell(player, card_obj)
    except ValueError:  # RULE 601.2f: the full price was not available
        return False
    engine.resolve_until_stable()
    return card_obj in engine.state.battlefield


def test_gagh_slinger_discounts_klingon_and_warrior_spells_only():
    engine, p1, p2 = game("Kruge, Genesis Seeker")
    on_battlefield(engine, "p1", "Gagh Slinger")
    kruge = p1.hand[0]  # {2}{R} Klingon Officer
    assert _cost_paid_for(engine, p1, kruge, {"C": 1, "R": 1})

    engine, p1, p2 = game()
    on_battlefield(engine, "p1", "Gagh Slinger")
    warrior = GameObject(Card(id="warr", name="Warr", type_line="Creature — Human Warrior", mana_cost_string="{1}{G}",
                              converted_mana_cost=2, is_creature=True, power=2, toughness=2),
                         owner_id="p1", zone=Zone.HAND)
    p1.hand.append(warrior)
    assert _cost_paid_for(engine, p1, warrior, {"G": 1})

    engine, p1, p2 = game()
    on_battlefield(engine, "p1", "Gagh Slinger")
    bear = GameObject(Card(id="bear", name="Bear", type_line="Creature — Bear", mana_cost_string="{1}{G}",
                           converted_mana_cost=2, is_creature=True, power=2, toughness=2),
                      owner_id="p1", zone=Zone.HAND)
    p1.hand.append(bear)
    assert not _cost_paid_for(engine, p1, bear, {"G": 1})


def test_kinga_class_battle_cruiser_targets_only_klingons_and_warriors():
    engine, p1, p2 = game("K't'inga-Class Battle Cruiser")
    kruge = on_battlefield(engine, "p1", "Kruge, Genesis Seeker")
    warrior = _tribal(engine, "p1", "W", "Creature — Human Warrior")
    bear = _tribal(engine, "p1", "B", "Creature — Bear")
    cast(engine, p1, p1.hand[0])
    offered = {o["label"] for o in engine.state.pending_choice["options"]}
    assert offered == {"Kruge, Genesis Seeker", "W"}  # RULE 115.1: the Bear is not a legal target
    engine.resolve_pending_choice(engine.state.pending_choice["options"][0]["id"])
    engine.resolve_until_stable()
    if engine.state.pending_choice:  # the second pick is optional ("one or two")
        engine.resolve_pending_choice("stop")
        engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert combat.has(kruge, "flying") and not combat.has(bear, "flying")


def test_promise_of_kahless_returns_both_types_but_not_the_sacrificed_card():
    engine, p1, p2 = game("The Promise of Kahless")
    fodder = _tribal(engine, "p1", "Fodder", "Creature — Klingon")
    dead = {}
    for name, type_line in (("Dead Klingon", "Creature — Klingon"), ("Dead Warrior", "Creature — Human Warrior"),
                            ("Dead Bear", "Creature — Bear")):
        obj = GameObject(Card(id=name, name=name, type_line=type_line, is_creature=True, power=1, toughness=1),
                         owner_id="p1", zone=Zone.GRAVEYARD)
        p1.graveyard.append(obj)
        dead[name] = obj
    cast(engine, p1, p1.hand[0])
    for _ in range(4):  # pay-or-decline, then pick the Klingon to sacrifice
        choice = engine.state.pending_choice
        if not choice:
            break
        option = next((o for o in choice["options"] if str(o.get("instance_id")) == str(fodder.instance_id)), None)
        engine.resolve_pending_choice(option["id"] if option else choice["options"][0]["id"])
        engine.resolve_until_stable()
    assert dead["Dead Klingon"] in engine.state.battlefield and dead["Dead Warrior"] in engine.state.battlefield
    assert dead["Dead Bear"] in p1.graveyard
    assert fodder in p1.graveyard  # RULE 109.1: "other" leaves the sacrificed card where it is


def test_union_search_filter_is_unchanged_for_single_type():
    # Regression guard: the single-type graveyard return keeps its scalar ``subtype`` parameter.
    result = _parse("Return all Elf creature cards from your graveyard to the battlefield.", sorcery=True)
    params = _effects(result)[0].params
    assert params["subtype"] == "elf" and "subtype_any" not in params


def test_push_the_limit_returns_mounts_and_vehicles_only_and_sacrifices_them_at_end_of_turn():
    from tests.support.star_trek import advance_to, stock_library

    engine, p1, p2 = game("Push the Limit", via_steps=True)
    stock_library(engine, "p1", 5)
    stock_library(engine, "p2", 5)
    for name, type_line, is_creature in (("Cart", "Artifact — Vehicle", False), ("Horse", "Creature — Mount", True),
                                         ("Bear", "Creature — Bear", True)):
        p1.graveyard.append(GameObject(
            Card(id=name, name=name, type_line=type_line, is_creature=is_creature, power=2 if is_creature else None,
                 toughness=2 if is_creature else None, vehicle_power=None if is_creature else 3,
                 vehicle_toughness=None if is_creature else 3),
            owner_id="p1", zone=Zone.GRAVEYARD))
    cast(engine, p1, p1.hand[0])
    assert {o.name for o in engine.state.battlefield} == {"Cart", "Horse"}  # RULE 205.3m: either type, not the Bear
    advance_to(engine, "end")
    engine.resolve_until_stable()
    assert not engine.state.battlefield

"""MEC-40 — cEDH Rocco's remaining 18 gaps, done to completion: Academy
Rector, Ajani Nacatl Pariah/Avenger, Allosaurus Shepherd, Domri Anarch of
Bolas, Eladamri Korvecdal, Elesh Norn Mother of Machines, Flamescroll
Celebrant, Food Chain, Gandalf the White, Guardian Project, Guardian
Sunmare, Kutzil Malamet Exemplar, Moon-Blessed Cleric, Sigarda Font of
Blessings, Squee the Immortal, Sylvan Library, The Jolly Balloon Man,
Yasharn Implacable Earth.

Reference: docs/implementation-state/Done_Backend.md "MEC-40" entry.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone

from tests.test_game_engine import creature, make_engine


def _etb_event(obj):
    return GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id=obj.controller_id, object=obj.name,
        instance_id=obj.instance_id, object_types=sorted(obj.type_words),
    )


def _attacks_event(obj):
    return GameEvent(
        EventType.ATTACKS, controller_id=obj.controller_id, object=obj.name,
        instance_id=obj.instance_id, object_types=sorted(obj.type_words),
    )


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def _cast(eng, p1, mana, hand_index=0):
    eng.begin_turn()
    eng.state.current_step = "main1"
    spell = p1.hand[hand_index]
    bind_from_catalogue(spell)
    p1.mana_pool.add_many(mana)
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()
    return spell


def _land(name="Forest"):
    return Card(id=name, name=name, type_line=f"Basic Land — {name}", is_land=True)


# ---------------------------------------------------------------------------
# Academy Rector
# ---------------------------------------------------------------------------


def test_academy_rector_dies_may_exile_and_search_enchantment_onto_battlefield():
    enchant = Card(id="Pacifism", name="Pacifism", type_line="Enchantment",
                    mana_cost_string="{1}{W}", converted_mana_cost=2)
    eng = make_engine([_named("Academy Rector")], hand=1)
    p1 = eng.state.player_by_id("p1")
    enchant_obj = GameObject(enchant, owner_id="p1", zone=Zone.LIBRARY)
    p1.library.append(enchant_obj)
    rector = _put(eng.state, _named("Academy Rector"), controller="p1")

    eng.rules.put_into_graveyard(rector)
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"
    eng.resolve_pending_choice("do")
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "search"
    pick = next(o for o in choice["options"] if o.get("instance_id") == enchant_obj.instance_id)
    eng.resolve_pending_choice(pick["id"])
    eng.resolve_until_stable()

    assert rector not in eng.state.battlefield
    assert rector not in p1.graveyard  # exiled, not left in graveyard
    assert any(o.card is enchant for o in eng.state.battlefield)


# ---------------------------------------------------------------------------
# Ajani, Nacatl Pariah
# ---------------------------------------------------------------------------


def test_ajani_etb_creates_cat_warrior_token():
    eng = make_engine([_named("Ajani, Nacatl Pariah")], hand=1)
    p1 = eng.state.player_by_id("p1")
    ajani = _put(eng.state, _named("Ajani, Nacatl Pariah"), controller="p1")
    eng.state.fire_event(_etb_event(ajani))
    eng.resolve_until_stable()
    assert any(o.card.name == "Cat Warrior" for o in eng.state.battlefield)


def test_ajani_exiles_self_when_another_cat_dies():
    eng = make_engine([_named("Ajani, Nacatl Pariah")], hand=1)
    ajani = _put(eng.state, _named("Ajani, Nacatl Pariah"), controller="p1")
    other_cat = _put(
        eng.state, creature("Cat Friend", type_line="Creature — Cat", power=1, toughness=1),
        controller="p1",
    )

    eng.rules.put_into_graveyard(other_cat)
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"
    eng.resolve_pending_choice("do")
    eng.resolve_until_stable()

    # `exile_return_transformed` is a real RULE 400.7 zone change, but this
    # engine's own implementation keeps the same `GameObject` reference
    # through it — the observable effect is the transformed back face.
    assert ajani in eng.state.battlefield
    assert ajani.card.name == "Ajani, Nacatl Avenger"


# ---------------------------------------------------------------------------
# Allosaurus Shepherd
# ---------------------------------------------------------------------------


def test_allosaurus_shepherd_protects_only_green_spells():
    eng = make_engine([_named("Allosaurus Shepherd")], hand=0)
    _put(eng.state, _named("Allosaurus Shepherd"), controller="p1")

    green_bolt = Card(id="Green Bolt", name="Green Bolt", type_line="Instant", is_instant=True,
                       mana_cost_string="{G}", converted_mana_cost=1, color_identity={"G"})
    red_bolt = Card(id="Red Bolt", name="Red Bolt", type_line="Instant", is_instant=True,
                     mana_cost_string="{R}", converted_mana_cost=1, color_identity={"R"})
    green_obj = GameObject(green_bolt, owner_id="p1", zone=Zone.STACK)
    red_obj = GameObject(red_bolt, owner_id="p1", zone=Zone.STACK)
    bind_from_catalogue(green_obj)
    bind_from_catalogue(red_obj)

    assert eng.rules._is_cant_be_countered(green_obj)
    assert not eng.rules._is_cant_be_countered(red_obj)


def test_allosaurus_shepherd_activated_ability_boosts_elves():
    eng = make_engine([_named("Allosaurus Shepherd")], hand=0)
    shepherd = _put(eng.state, _named("Allosaurus Shepherd"), controller="p1")
    elf = _put(eng.state, creature("Elf Friend", type_line="Creature — Elf", power=1, toughness=1), controller="p1")
    bear = _put(eng.state, creature("Bear"), controller="p1")

    eng.rules.add_mana(eng.state.player_by_id("p1"), "G", 6)
    eng.activate_ability(eng.state.player_by_id("p1"), shepherd, ability_index=0)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()

    assert elf.power == 5 and elf.toughness == 5
    assert "dinosaur" in {s.lower() for s in elf._added_subtypes}
    assert bear.power != 5 or bear.toughness != 5


# ---------------------------------------------------------------------------
# Domri, Anarch of Bolas
# ---------------------------------------------------------------------------


def test_domri_plus_one_produces_mana_and_protects_creature_spells_this_turn():
    eng = make_engine([_named("Domri, Anarch of Bolas")], [creature("Big Guy", power=5, toughness=5)], hand=1)
    p1 = eng.state.player_by_id("p1")
    domri = _put(eng.state, _named("Domri, Anarch of Bolas"), controller="p1")
    eng.begin_turn()
    eng.state.current_step = "main1"

    eng.activate_ability(p1, domri, ability_index=0)
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "add_mana_any_color"
    eng.resolve_pending_choice("R")
    eng.resolve_until_stable()
    assert p1.mana_pool.pool.get("R", 0) == 1

    creature_spell = Card(id="A Creature", name="A Creature", type_line="Creature — Bear",
                           mana_cost_string="{1}{G}", converted_mana_cost=2, is_creature=True,
                           power=2, toughness=2)
    obj = GameObject(creature_spell, owner_id="p1", zone=Zone.HAND)
    p1.hand.append(obj)
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"G": 1, "C": 1})
    eng.cast_spell(p1, obj)

    from mtg_analyzer.game.effects import CantBeCounteredEffect

    assert any(isinstance(e, CantBeCounteredEffect) for e in obj.spell_effects)


# ---------------------------------------------------------------------------
# Eladamri, Korvecdal
# ---------------------------------------------------------------------------


def test_eladamri_top_library_permission_is_creature_only():
    eng = make_engine([_named("Eladamri, Korvecdal")], hand=0)
    _put(eng.state, _named("Eladamri, Korvecdal"), controller="p1")

    from mtg_analyzer.game.top_library import may_cast_spell_from_top_of_library

    p1 = eng.state.player_by_id("p1")
    creature_card = creature("Top Creature")
    noncreature_card = Card(id="Top Sorcery", name="Top Sorcery", type_line="Sorcery",
                             is_sorcery=True, mana_cost_string="{1}", converted_mana_cost=1)
    assert may_cast_spell_from_top_of_library(p1, eng.state, creature_card)
    assert not may_cast_spell_from_top_of_library(p1, eng.state, noncreature_card)


def test_eladamri_reveal_ability_puts_revealed_creature_onto_battlefield():
    eng = make_engine([_named("Eladamri, Korvecdal")], hand=1)
    p1 = eng.state.player_by_id("p1")
    eladamri = _put(eng.state, _named("Eladamri, Korvecdal"), controller="p1")
    tapper1 = _put(eng.state, creature("Tapper1"), controller="p1")
    tapper2 = _put(eng.state, creature("Tapper2"), controller="p1")
    hand_creature = creature("Hand Creature")
    hand_obj = GameObject(hand_creature, owner_id="p1", zone=Zone.HAND)
    p1.hand.append(hand_obj)
    bind_from_catalogue(hand_obj)

    p1.mana_pool.add_many({"G": 1})
    eng.begin_turn()
    eng.state.current_step = "main1"
    eng.activate_ability(
        p1, eladamri, ability_index=0, tap_choices=[tapper1.instance_id, tapper2.instance_id],
    )
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "search"
    pick = next(o for o in choice["options"] if o.get("instance_id") == hand_obj.instance_id)
    eng.resolve_pending_choice(pick["id"])
    eng.resolve_until_stable()

    assert hand_obj in eng.state.battlefield


# ---------------------------------------------------------------------------
# Elesh Norn, Mother of Machines
# ---------------------------------------------------------------------------


def test_elesh_norn_doubles_own_etb_trigger():
    from mtg_analyzer.models.events import EventType, GameEvent

    eng = make_engine([_named("Elesh Norn, Mother of Machines")], hand=1)
    p1 = eng.state.player_by_id("p1")
    _put(eng.state, _named("Elesh Norn, Mother of Machines"), controller="p1")
    rector = _put(eng.state, _named("Academy Rector"), controller="p1")

    from mtg_analyzer.game.continuous import trigger_doubler_bonus

    event = GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=rector.instance_id)
    assert trigger_doubler_bonus(eng.state, rector, event=event) == 1


def test_elesh_norn_suppresses_only_opponents_etb_triggers():
    from mtg_analyzer.models.events import EventType, GameEvent

    eng = make_engine([_named("Elesh Norn, Mother of Machines")], [creature("Opp Bear")], hand=0)
    _put(eng.state, _named("Elesh Norn, Mother of Machines"), controller="p1")
    opp_permanent = _put(eng.state, creature("Opp Trigger Bear"), controller="p2")
    own_permanent = _put(eng.state, creature("Own Trigger Bear"), controller="p1")

    from mtg_analyzer.game.continuous import trigger_suppressed_for

    event = GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=opp_permanent.instance_id)
    assert trigger_suppressed_for(eng.state, event, "p2") is True
    assert trigger_suppressed_for(eng.state, event, "p1") is False


# ---------------------------------------------------------------------------
# Flamescroll Celebrant
# ---------------------------------------------------------------------------


def test_flamescroll_celebrant_damages_opponent_activating_non_mana_ability():
    eng = make_engine(
        [_named("Flamescroll Celebrant")], [_named("Flamescroll Celebrant")], hand=0,
    )
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    celebrant = _put(eng.state, _named("Flamescroll Celebrant"), controller="p1")
    opp_creature = _put(eng.state, _named("Flamescroll Celebrant"), controller="p2")

    before = p2.life
    p2.mana_pool.add_many({"R": 1, "C": 1})
    eng.activate_ability(p2, opp_creature, ability_index=0)
    eng.resolve_until_stable()

    assert p2.life == before - 1
    assert celebrant in eng.state.battlefield


# ---------------------------------------------------------------------------
# Food Chain
# ---------------------------------------------------------------------------


def test_food_chain_produces_mana_equal_to_one_plus_exiled_creature_mv():
    eng = make_engine([_named("Food Chain")], hand=0)
    p1 = eng.state.player_by_id("p1")
    _put(eng.state, _named("Food Chain"), controller="p1")
    victim = _put(eng.state, creature("Victim", cost="{3}{G}", power=3, toughness=3), controller="p1")

    from mtg_analyzer.game.mana_abilities import mana_abilities_for

    food_chain_obj = next(o for o in eng.state.battlefield if o.card.name == "Food Chain")
    abilities = mana_abilities_for(food_chain_obj, state=eng.state)
    assert len(abilities) == 1
    eng.tap_for_mana(
        p1, food_chain_obj, option_index=0, ability_index=0, sacrifice_choice=victim.instance_id,
    )
    assert victim not in eng.state.battlefield
    assert victim in p1.exile
    assert p1.mana_pool.total() == 5  # 1 + 4 (converted mana cost) — restricted to creature spells


# ---------------------------------------------------------------------------
# Gandalf the White
# ---------------------------------------------------------------------------


def test_gandalf_flash_permission_is_scoped_to_legendary_and_artifact():
    eng = make_engine([_named("Gandalf the White")], hand=0)
    _put(eng.state, _named("Gandalf the White"), controller="p1")

    from mtg_analyzer.game.continuous import has_standing_flash_permission

    p1 = eng.state.player_by_id("p1")
    legendary_card = Card(
        id="Legendary Guy", name="Legendary Guy", type_line="Legendary Creature — Human",
        is_creature=True, is_legendary=True, mana_cost_string="{2}", converted_mana_cost=2,
        power=2, toughness=2,
    )
    plain_card = creature("Plain Bear")
    assert has_standing_flash_permission(eng.state, p1, legendary_card)
    assert not has_standing_flash_permission(eng.state, p1, plain_card)


def test_gandalf_doubles_trigger_for_legendary_or_artifact_entering_or_leaving():
    from mtg_analyzer.models.events import EventType, GameEvent

    eng = make_engine([_named("Gandalf the White")], hand=0)
    _put(eng.state, _named("Gandalf the White"), controller="p1")
    legendary_card = Card(
        id="Legendary Guy 2", name="Legendary Guy 2", type_line="Legendary Creature — Human",
        is_creature=True, is_legendary=True, mana_cost_string="{2}", converted_mana_cost=2,
        power=2, toughness=2,
    )
    legendary_obj = _put(eng.state, legendary_card, controller="p1")
    plain_obj = _put(eng.state, creature("Plain Guy"), controller="p1")

    from mtg_analyzer.game.continuous import trigger_doubler_bonus

    enter_event = GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=legendary_obj.instance_id)
    leave_event = GameEvent(EventType.LEAVES_BATTLEFIELD, instance_id=legendary_obj.instance_id)
    plain_event = GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=plain_obj.instance_id)
    assert trigger_doubler_bonus(eng.state, legendary_obj, event=enter_event) == 1
    assert trigger_doubler_bonus(eng.state, legendary_obj, event=leave_event) == 1
    assert trigger_doubler_bonus(eng.state, plain_obj, event=plain_event) == 0


# ---------------------------------------------------------------------------
# Guardian Project
# ---------------------------------------------------------------------------


def test_guardian_project_draws_for_unique_name_but_not_a_repeat():
    eng = make_engine([_named("Guardian Project")], hand=1)
    p1 = eng.state.player_by_id("p1")
    p1.library.append(GameObject(_land("Deck Filler"), owner_id="p1", zone=Zone.LIBRARY))
    p1.library.append(GameObject(_land("Deck Filler 2"), owner_id="p1", zone=Zone.LIBRARY))
    _put(eng.state, _named("Guardian Project"), controller="p1")
    first = creature("Unique Bear")
    first_obj = GameObject(first, owner_id="p1", zone=Zone.HAND)
    p1.hand.append(first_obj)
    bind_from_catalogue(first_obj)

    before = len(p1.library)
    eng.state.add_to_battlefield(first_obj)
    p1.hand.remove(first_obj)
    eng.state.fire_event(_etb_event(first_obj))
    eng.resolve_until_stable()
    assert len(p1.library) == before - 1  # drew a card

    second = creature("Unique Bear")  # same name
    second_obj = GameObject(second, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(second_obj)
    eng.state.add_to_battlefield(second_obj)
    before2 = len(p1.library)
    eng.state.fire_event(_etb_event(second_obj))
    eng.resolve_until_stable()
    assert len(p1.library) == before2  # no draw — shares a name


# ---------------------------------------------------------------------------
# Guardian Sunmare
# ---------------------------------------------------------------------------


def test_guardian_sunmare_saddle_then_attack_triggers_search():
    eng = make_engine([_named("Guardian Sunmare")], hand=1)
    p1 = eng.state.player_by_id("p1")
    sunmare = _put(eng.state, _named("Guardian Sunmare"), controller="p1")
    saddler = _put(eng.state, creature("Saddler", power=4, toughness=4), controller="p1")
    small_artifact = Card(id="Signet", name="Signet", type_line="Artifact",
                           mana_cost_string="{2}", converted_mana_cost=2)
    artifact_obj = GameObject(small_artifact, owner_id="p1", zone=Zone.LIBRARY)
    p1.library.append(artifact_obj)
    eng.begin_turn()
    eng.state.current_step = "main1"

    eng.activate_ability(p1, sunmare, ability_index=0, tap_choices=[saddler.instance_id])
    eng.resolve_until_stable()
    assert sunmare.saddled_until_turn == eng.state.internal_turn.number

    eng.state.fire_event(_attacks_event(sunmare))
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "search"
    pick = next(o for o in choice["options"] if o.get("instance_id") == artifact_obj.instance_id)
    eng.resolve_pending_choice(pick["id"])
    eng.resolve_until_stable()
    assert any(o.card is small_artifact for o in eng.state.battlefield)


def test_guardian_sunmare_attacks_without_saddled_does_not_trigger():
    eng = make_engine([_named("Guardian Sunmare")], hand=0)
    p1 = eng.state.player_by_id("p1")
    sunmare = _put(eng.state, _named("Guardian Sunmare"), controller="p1")
    small_artifact = Card(id="Signet2", name="Signet2", type_line="Artifact",
                           mana_cost_string="{2}", converted_mana_cost=2)
    p1.library.append(GameObject(small_artifact, owner_id="p1", zone=Zone.LIBRARY))

    eng.state.fire_event(_attacks_event(sunmare))
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None
    assert not any(o.card is small_artifact for o in eng.state.battlefield)


# ---------------------------------------------------------------------------
# Kutzil, Malamet Exemplar
# ---------------------------------------------------------------------------


def test_kutzil_opponents_cant_cast_during_your_turn():
    eng = make_engine([_named("Kutzil, Malamet Exemplar")], [creature("Opp Bear")], hand=0)
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    _put(eng.state, _named("Kutzil, Malamet Exemplar"), controller="p1")
    eng.begin_turn()
    eng.state.current_step = "main1"
    assert eng.state.active_player.id == "p1"

    bolt = Card(id="P2 Bolt", name="P2 Bolt", type_line="Instant", is_instant=True,
                mana_cost_string="{R}", converted_mana_cost=1,
                oracle_text="~ deals 2 damage to any target.")
    bolt_obj = GameObject(bolt, owner_id="p2", zone=Zone.HAND)
    p2.hand.append(bolt_obj)
    bind_from_catalogue(bolt_obj)
    p2.mana_pool.add_many({"R": 1})
    assert not eng.can_cast(p2, bolt_obj)


def test_kutzil_draws_when_boosted_creature_deals_combat_damage():
    from mtg_analyzer.models.events import EventType, GameEvent

    eng = make_engine([_named("Kutzil, Malamet Exemplar")], hand=1)
    p1 = eng.state.player_by_id("p1")
    p1.library.append(GameObject(_land("Deck Filler"), owner_id="p1", zone=Zone.LIBRARY))
    _put(eng.state, _named("Kutzil, Malamet Exemplar"), controller="p1")

    before = len(p1.library)
    event = GameEvent(
        EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER,
        player_id="p1", target_id="p2", max_power=5, amount=5, subtypes=[],
        contributor_is_commander=False, contributor_power_gt_base=True,
    )
    eng.state.fire_event(event)
    eng.resolve_until_stable()
    assert len(p1.library) == before - 1


# ---------------------------------------------------------------------------
# Moon-Blessed Cleric
# ---------------------------------------------------------------------------


def test_moon_blessed_cleric_puts_searched_enchantment_on_top():
    eng = make_engine([_named("Moon-Blessed Cleric")], hand=1)
    p1 = eng.state.player_by_id("p1")
    enchant = Card(id="Rancor2", name="Rancor2", type_line="Enchantment — Aura",
                    mana_cost_string="{G}", converted_mana_cost=1)
    enchant_obj = GameObject(enchant, owner_id="p1", zone=Zone.LIBRARY)
    p1.library.append(enchant_obj)

    cleric = p1.hand[0]
    bind_from_catalogue(cleric)
    p1.mana_pool.add_many({"W": 1, "C": 2})
    eng.begin_turn()
    eng.state.current_step = "main1"
    eng.cast_spell(p1, cleric)
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"
    eng.resolve_pending_choice("do")
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "search"
    pick = next(o for o in choice["options"] if o.get("instance_id") == enchant_obj.instance_id)
    eng.resolve_pending_choice(pick["id"])
    eng.resolve_until_stable()

    assert p1.library[-1] is enchant_obj


# ---------------------------------------------------------------------------
# Sigarda, Font of Blessings
# ---------------------------------------------------------------------------


def test_sigarda_top_library_permission_covers_angel_and_human_only():
    eng = make_engine([_named("Sigarda, Font of Blessings")], hand=0)
    _put(eng.state, _named("Sigarda, Font of Blessings"), controller="p1")

    from mtg_analyzer.game.top_library import may_cast_spell_from_top_of_library

    p1 = eng.state.player_by_id("p1")
    angel_card = Card(id="Top Angel", name="Top Angel", type_line="Creature — Angel", is_creature=True,
                       mana_cost_string="{3}{W}", converted_mana_cost=4, power=3, toughness=3)
    human_card = Card(id="Top Human", name="Top Human", type_line="Creature — Human", is_creature=True,
                       mana_cost_string="{1}{W}", converted_mana_cost=2, power=1, toughness=1)
    bear_card = creature("Top Bear")
    assert may_cast_spell_from_top_of_library(p1, eng.state, angel_card)
    assert may_cast_spell_from_top_of_library(p1, eng.state, human_card)
    assert not may_cast_spell_from_top_of_library(p1, eng.state, bear_card)


# ---------------------------------------------------------------------------
# Squee, the Immortal
# ---------------------------------------------------------------------------


def test_squee_castable_from_graveyard_and_exile():
    eng = make_engine([_named("Squee, the Immortal")], hand=0)
    p1 = eng.state.player_by_id("p1")
    eng.begin_turn()
    eng.state.current_step = "main1"
    squee_card = _named("Squee, the Immortal")
    grave_obj = GameObject(squee_card, owner_id="p1", zone=Zone.GRAVEYARD)
    bind_from_catalogue(grave_obj)
    p1.graveyard.append(grave_obj)
    p1.mana_pool.add_many({"R": 2, "C": 1})
    assert eng.can_cast(p1, grave_obj)

    p1.graveyard.remove(grave_obj)
    exile_obj = GameObject(squee_card, owner_id="p1", zone=Zone.EXILE)
    bind_from_catalogue(exile_obj)
    p1.exile.append(exile_obj)
    assert eng.can_cast(p1, exile_obj)


# ---------------------------------------------------------------------------
# Sylvan Library
# ---------------------------------------------------------------------------


def test_sylvan_library_draws_two_and_pay_or_return_for_each():
    eng = make_engine([_named("Sylvan Library")], hand=1)
    p1 = eng.state.player_by_id("p1")
    _put(eng.state, _named("Sylvan Library"), controller="p1")
    for i in range(3):
        p1.library.append(GameObject(_land(f"Card{i}"), owner_id="p1", zone=Zone.LIBRARY))

    eng.begin_turn()
    while eng.state.current_step != "draw":
        eng.advance_step()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"
    eng.resolve_pending_choice("do")
    eng.resolve_until_stable()

    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "pay_life_or_return_to_library"
    before_life = p1.life
    first_id = choice["instance_id"]
    eng.resolve_pending_choice("pay")
    assert p1.life == before_life - 4

    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "pay_life_or_return_to_library"
    second_id = choice["instance_id"]
    assert second_id != first_id
    eng.resolve_pending_choice("return")

    assert eng.state.pending_choice is None
    returned = eng.state.find_object(second_id)
    assert returned in p1.library
    assert returned is p1.library[-1]


# ---------------------------------------------------------------------------
# The Jolly Balloon Man
# ---------------------------------------------------------------------------


def test_jolly_balloon_man_copies_with_1_1_and_sacrifices_at_end_step():
    eng = make_engine([_named("The Jolly Balloon Man")], hand=0)
    p1 = eng.state.player_by_id("p1")
    man = _put(eng.state, _named("The Jolly Balloon Man"), controller="p1")
    target = _put(eng.state, creature("Big Target", power=6, toughness=6), controller="p1")
    eng.begin_turn()
    eng.state.current_step = "main1"

    p1.mana_pool.add_many({"C": 1})
    eng.activate_ability(p1, man, ability_index=0, targets=[target])
    eng.resolve_until_stable()

    token = next(o for o in eng.state.battlefield if o.card.name == "Big Target" and o is not target)
    assert token.power == 1 and token.toughness == 1
    assert "balloon" in token.card.type_line.lower()
    assert "flying" in token.temp_keywords
    assert "haste" in token.temp_keywords
    assert len(eng.state.delayed_triggers) == 1

    while eng.state.current_step != "end":
        eng.advance_step()
    eng.resolve_until_stable()
    assert token not in eng.state.battlefield


# ---------------------------------------------------------------------------
# Yasharn, Implacable Earth
# ---------------------------------------------------------------------------


def test_yasharn_etb_searches_forest_and_plains():
    eng = make_engine([_named("Yasharn, Implacable Earth")], hand=1)
    p1 = eng.state.player_by_id("p1")
    forest = _land("Forest")
    plains = _land("Plains")
    forest_obj = GameObject(forest, owner_id="p1", zone=Zone.LIBRARY)
    plains_obj = GameObject(plains, owner_id="p1", zone=Zone.LIBRARY)
    p1.library.append(forest_obj)
    p1.library.append(plains_obj)

    yasharn = p1.hand[0]
    bind_from_catalogue(yasharn)
    p1.mana_pool.add_many({"G": 1, "W": 1, "C": 2})
    eng.begin_turn()
    eng.state.current_step = "main1"
    eng.cast_spell(p1, yasharn)
    eng.resolve_until_stable()

    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "search"
    pick = next(o for o in choice["options"] if o.get("instance_id") == forest_obj.instance_id)
    eng.resolve_pending_choice(pick["id"])
    eng.resolve_until_stable()

    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "search"
    pick = next(o for o in choice["options"] if o.get("instance_id") == plains_obj.instance_id)
    eng.resolve_pending_choice(pick["id"])
    eng.resolve_until_stable()

    assert forest_obj in p1.hand
    assert plains_obj in p1.hand


def test_yasharn_blocks_pay_life_and_nonland_sacrifice_costs():
    eng = make_engine([_named("Yasharn, Implacable Earth")], hand=0)
    p1 = eng.state.player_by_id("p1")
    _put(eng.state, _named("Yasharn, Implacable Earth"), controller="p1")

    from mtg_analyzer.game.continuous import cost_restricted

    assert cost_restricted(eng.state, "pay_life")
    assert cost_restricted(eng.state, "sacrifice_nonland_permanent")

    payer = Card(
        id="Life Payer", name="Life Payer", type_line="Creature — Human", is_creature=True,
        mana_cost_string="{1}", converted_mana_cost=1, power=1, toughness=1,
        oracle_text="Pay 1 life: Scry 1.",
    )
    payer_obj = _put(eng.state, payer, controller="p1")
    assert payer_obj.activated_abilities
    assert not eng.can_activate(p1, payer_obj, payer_obj.activated_abilities[0])

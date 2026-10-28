"""PAR-185 shared animation quantities, selectors and independent durations."""
from __future__ import annotations

import pytest
from mtg_analyzer.game import mana_abilities  # noqa: F401
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext, _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.game import land, make_engine, obj_on_battlefield
from tests.test_land_animate_family import _named


@pytest.mark.parametrize("name", [
    "Cactus Preserve", "Jolrael, Voice of Zhalfir", "Obuun, Mul Daya Ancestor", "Vastwood Animist",
    "Liege of the Tangle", "Kormus Bell", "Living Lands", "Living Plane", "Nature's Revolt",
    "Jolrael, Empress of Beasts", "Soulstone Sanctuary", "Stalking Stones", "Sylvan Awakening",
    "Rude Awakening", "Thelonite Druid", "Wrenn and Realmbreaker",
])
def test_real_animation_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled


def _board():
    eng = make_engine([], [], hand=0)
    forest = obj_on_battlefield(eng.state, eng, land(), controller="p1")
    source = obj_on_battlefield(eng.state, eng, _named("Obuun, Mul Daya Ancestor"), controller="p1")
    return eng, source, forest


def test_hand_size_animation_measures_once_and_survives_clone():
    eng, source, forest = _board()
    player = eng.state.player_by_id("p1")
    player.hand.extend(GameObject(land(str(i)), owner_id="p1", zone=Zone.HAND) for i in range(3))
    body = ("up to 1 target land you control becomes an x/x green and blue bird creature with flying and haste "
            "until end of turn, where x is the number of cards in your hand. it's still a land")
    specs = parse_effect_body(body)
    effect = build_effects(specs, source)[0]
    assert len(effect.target_specs) == 1 and effect.target_specs[0].optional
    effect.apply(GameContext(eng.state, eng.rules), [forest])
    assert (forest.power, forest.toughness) == (3, 3)
    player.hand.clear()
    clone = GameEngine(eng.state.clone())
    clone.recompute_continuous_effects()
    changed = clone.state.find_object(forest.instance_id)
    assert (changed.power, changed.toughness) == (3, 3)
    assert changed.granted_keywords >= {"flying", "haste"}


@pytest.mark.parametrize("power", [5, -2])
def test_source_power_animation_sets_signed_snapshot(power):
    eng, source, forest = _board()
    source.temp_power = power - int(source.card.power)
    eng.recompute_continuous_effects()
    assert source.power == power
    specs = parse_effect_body("target land you control becomes an x/x elemental creature with trample and haste "
                              "until end of turn, where x is ~'s power. it's still a land")
    build_effects(specs, source)[0].apply(GameContext(eng.state, eng.rules), [forest])
    # RULE 107.1b / 611.2d: setting P/T keeps a negative calculated value,
    # and the chosen value is not recalculated when the source changes.
    assert (forest.power, forest.toughness) == (power, power)
    source.temp_power += 4
    eng.recompute_continuous_effects()
    assert (forest.power, forest.toughness) == (power, power)


def test_source_power_modifier_clamps_a_negative_result_instead_of_setting_pt():
    eng, source, forest = _board()
    source.temp_power = -5
    eng.recompute_continuous_effects()
    before = (source.power, source.toughness)
    specs = parse_effect_body("~ gets +x/+x until end of turn, where x is ~'s power")
    build_effects(specs, source)[0].apply(GameContext(eng.state, eng.rules))
    eng.recompute_continuous_effects()
    assert (source.power, source.toughness) == before


@pytest.mark.parametrize("departure", ["destroy", "blink"])
def test_pending_obuun_animation_measures_departed_source_visit_through_clone(departure):
    eng, source, forest = _board()
    bind_from_catalogue(source)
    eng.rules._place_trigger(source.triggered_abilities[0], targets=[forest])
    # Change the source after triggering. The measurement must use the
    # last battlefield value, not its trigger-time or later-visit value.
    source.temp_power = 4
    eng.rules.add_counters(source, 2, "+1/+1")
    eng.recompute_continuous_effects()
    assert source.power == 9
    getattr(eng.rules, departure)(source)
    if departure == "blink":
        eng.rules.add_counters(source, 5, "+1/+1")
        eng.recompute_continuous_effects()
        assert source.power == 8
    clone = GameEngine(eng.state.clone())
    clone.resolve_until_stable()
    clone.recompute_continuous_effects()
    changed = clone.state.find_object(forest.instance_id)
    assert changed.is_creature and (changed.power, changed.toughness) == (9, 9)


@pytest.mark.parametrize("name", ["Sarkhan, the Dragonspeaker", "Lurking Evil", "Chimeric Coils", "Chimeric Staff"])
def test_nonland_type_replacement_is_supported_by_par217(name):
    eng = make_engine([], [], hand=0)
    card = _named(name)
    assert parse_oracle(card).modeled
    source = obj_on_battlefield(eng.state, eng, card, controller="p1")
    bind_from_catalogue(source)
    assert source.activated_abilities


@pytest.mark.parametrize("name", [
    "Hidden Ancients", "Hidden Gibbons", "Hidden Guerrillas", "Hidden Spider",
    "Opal Archangel", "Opal Caryatid", "Opal Champion", "Opal Gargoyle",
    "Veil of Birds", "Veiled Apparition", "Veiled Serpent", "Iron Man Armor",
])
def test_source_pronoun_binds_enchantment_type_replacement_after_par217(name):
    eng = make_engine([], [], hand=0)
    card = _named(name)
    assert parse_oracle(card).modeled
    source = obj_on_battlefield(eng.state, eng, card, controller="p1")
    bind_from_catalogue(source)
    assert source.triggered_abilities
    eng.recompute_continuous_effects()
    assert not source.is_creature


@pytest.mark.parametrize("body", [
    "it becomes a 3/3 knight creature with first strike",
    "it becomes a 4/4 ape creature until end of turn",
    "it becomes a 0/0 construct hero artifact creature with flying until end of turn",
    'it becomes a 3/3 illusion creature with flying and "at the beginning of your upkeep, sacrifice ~ unless you pay {1}{u}."',
])
def test_source_pronoun_replacement_requires_a_bound_source_reading(body):
    from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading
    assert parse_effect_body(body, reading=ClauseReading(self_subject=True))
    assert parse_effect_body(body) is None


@pytest.mark.parametrize("body", [
    "target land becomes an x/x creature until end of turn",
    "it becomes a legendary 4/4 dragon creature until end of turn",
])
def test_singular_target_and_previous_forms_can_replace_types_after_par217(body):
    from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading
    assert parse_effect_body(body, reading=ClauseReading(previous_subject=True))


def test_liege_counter_durations_expire_independently_and_never_restart():
    eng, source, first = _board()
    second = obj_on_battlefield(eng.state, eng, land("Island", "Island"), controller="p1")
    liege = obj_on_battlefield(eng.state, eng, _named("Liege of the Tangle"), controller="p1")
    bind_from_catalogue(liege)
    effects = liege.triggered_abilities[0].effects
    assert sum(len(e.target_specs) for e in effects) == 1
    _apply_effects_partitioned(effects, eng.rules.context, [first, second], None, source=liege)
    assert first.counters.get("awakening") == second.counters.get("awakening") == 1
    assert first.is_creature and second.is_creature
    assert (first.power, second.power) == (8, 8)
    clone = GameEngine(eng.state.clone())
    changed = clone.state.find_object(first.instance_id)
    untouched = clone.state.find_object(second.instance_id)
    clone.rules.add_counters(changed, -1, "awakening")
    clone.recompute_continuous_effects()
    assert not changed.is_creature and untouched.is_creature
    clone.rules.add_counters(changed, 1, "awakening")
    clone.recompute_continuous_effects()
    assert not changed.is_creature and untouched.power == 8
    clone.rules.blink(untouched)
    clone.recompute_continuous_effects()
    assert not untouched.is_creature
    assert first.is_creature and second.is_creature


def test_global_swamp_static_tracks_both_players_and_later_entries():
    eng = make_engine([], [], hand=0)
    bell = obj_on_battlefield(eng.state, eng, _named("Kormus Bell"), controller="p1")
    bind_from_catalogue(bell)
    first = obj_on_battlefield(eng.state, eng, land("Swamp", "Swamp"), controller="p1")
    other = obj_on_battlefield(eng.state, eng, land("Other Swamp", "Swamp"), controller="p2")
    forest = obj_on_battlefield(eng.state, eng, land(), controller="p1")
    eng.recompute_continuous_effects()
    assert first.is_creature and other.is_creature and not forest.is_creature
    late = obj_on_battlefield(eng.state, eng, land("Later Swamp", "Swamp"), controller="p2")
    eng.recompute_continuous_effects()
    assert late.is_creature and late.is_land and late.power == 1


def test_target_player_mass_animation_uses_only_that_players_existing_lands():
    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    player = eng.state.player_by_id("p1")
    opponent = eng.state.player_by_id("p2")
    player.hand.extend(GameObject(land(str(i)), owner_id="p1", zone=Zone.HAND) for i in range(2))
    player.mana_pool.add_many({"G": 1, "C": 2})
    source = obj_on_battlefield(eng.state, eng, _named("Jolrael, Empress of Beasts"), controller="p1")
    bind_from_catalogue(source)
    ours = obj_on_battlefield(eng.state, eng, land(), controller="p1")
    theirs = obj_on_battlefield(eng.state, eng, land("Island", "Island"), controller="p2")
    eng.activate_ability(player, source, ability_index=0, targets=[opponent])
    clone = GameEngine(eng.state.clone())
    clone.resolve_until_stable()
    late = obj_on_battlefield(clone.state, clone, land("Later Swamp", "Swamp"), controller="p2")
    clone.recompute_continuous_effects()
    assert clone.state.find_object(theirs.instance_id).is_creature
    assert clone.state.find_object(theirs.instance_id).power == 3
    assert not clone.state.find_object(ours.instance_id).is_creature
    assert not late.is_creature
    assert not theirs.is_creature


@pytest.mark.parametrize("answer,damage", [("pay", 3), ("decline", 0)])
def test_animated_ward_is_a_real_triggered_payment_and_expires(answer, damage):
    from mtg_analyzer.game import durations
    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    player = eng.state.player_by_id("p1")
    player.mana_pool.add_many({"R": 1, "C": 3})
    hall = obj_on_battlefield(eng.state, eng, _named("Hall of Storm Giants"), controller="p2")
    specs = parse_effect_body("until end of turn, ~ becomes a 7/7 blue giant creature with ward {3}. it's still a land")
    build_effects(specs, hall)[0].apply(GameContext(eng.state, eng.rules))
    assert hall.granted_ward_cost == "{3}"
    spell = GameObject(_named("Lightning Bolt"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    player.hand.append(spell)
    eng.cast_spell(player, spell, targets=[hall])
    assert len(eng.state.stack) == 2
    clone = GameEngine(eng.state.clone())
    clone.resolve_until_stable()
    assert clone.state.pending_choice["kind"] == "ward"
    clone.resolve_pending_choice(answer)
    changed = clone.state.find_object(hall.instance_id)
    assert changed.damage_marked == damage
    durations.sweep(clone.state, "cleanup")
    clone.recompute_continuous_effects()
    assert changed.granted_ward_cost is None and not changed.is_creature


def test_legendary_enchanted_land_uses_the_registered_supertype_flag():
    eng, source, forest = _board()
    source.attached_to = forest.instance_id
    specs = parse_effect_body("enchanted land becomes a legendary 8/12 spirit creature with trample "
                              "until end of turn. it's still a land")
    build_effects(specs, source)[0].apply(GameContext(eng.state, eng.rules))
    assert forest.is_land and forest.is_creature and forest.is_legendary
    assert (forest.power, forest.toughness) == (8, 12)
    assert "trample" in forest.granted_keywords


def test_permanent_self_animation_outlives_cleanup_but_not_a_zone_visit():
    from mtg_analyzer.game import durations
    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    player = eng.state.player_by_id("p1")
    player.mana_pool.add_many({"C": 4})
    sanctuary = obj_on_battlefield(eng.state, eng, _named("Soulstone Sanctuary"), controller="p1")
    bind_from_catalogue(sanctuary)
    eng.activate_ability(player, sanctuary, ability_index=0)
    eng.resolve_until_stable()
    durations.sweep(eng.state, "cleanup")
    eng.recompute_continuous_effects()
    assert sanctuary.is_land and sanctuary.is_creature and sanctuary.has_subtype("Dragon")
    eng.rules.blink(sanctuary)
    eng.recompute_continuous_effects()
    assert not sanctuary.is_creature


def test_next_turn_mass_animation_expires_on_its_owners_turn():
    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    source = obj_on_battlefield(eng.state, eng, land(), controller="p1")
    specs = parse_effect_body("until your next turn, all lands you control become 2/2 elemental creatures "
                              "with reach, indestructible, and haste. they're still lands")
    build_effects(specs, source)[0].apply(GameContext(eng.state, eng.rules))
    assert source.is_creature and source.power == 2
    eng.begin_turn()
    eng.recompute_continuous_effects()
    assert source.is_creature
    eng.begin_turn()
    eng.recompute_continuous_effects()
    assert not source.is_creature


def test_paid_x_animation_enforces_its_printed_minimum():
    from mtg_analyzer.models.cards.card import Card
    card = Card(id="Lair ability", name="Lair ability", type_line="Land", is_land=True,
                oracle_text="{X}{G}: Until end of turn, this land becomes an X/X green Hydra creature. "
                            "It's still a land. X can't be 0.")
    assert parse_oracle(card).modeled
    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    player = eng.state.player_by_id("p1")
    player.mana_pool.add_many({"G": 1, "C": 3})
    source = obj_on_battlefield(eng.state, eng, card, controller="p1")
    bind_from_catalogue(source)
    with pytest.raises(ValueError, match="X must be at least"):
        eng.activate_ability(player, source, ability_index=0, x=0)
    eng.activate_ability(player, source, ability_index=0, x=3)
    eng.resolve_until_stable()
    assert source.is_creature and source.is_land and source.power == source.toughness == 3


@pytest.mark.parametrize("name", ["Genju of the Fields",
                                  "Hunting Wilds", "Hive of the Eye Tyrant"])
# Cyclone Sire / Noyan Dar left this list in PAR-204 (targeted antecedent + "if you do", test_par204_optional_payment.py).
def test_independent_outer_or_inner_grammar_stays_fail_closed(name):
    assert not parse_oracle(_named(name)).modeled


def test_unsupported_plural_body_still_fails_closed():
    assert parse_effect_body("all lands become x/x construct artifact creatures until end of turn") is None

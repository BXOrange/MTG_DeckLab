"""Deep Space 9's current exile pool and Borg Incursion's one-color group grant."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import EffectRegistry
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.star_trek import advance_to, cast, game, vanilla


def _card(name):
    if name == "Deep Space 9":
        return Card(id="ds9", name=name, type_line="Legendary Artifact — Spacecraft", is_legendary=True,
            mana_cost_string="{9}", converted_mana_cost=9, keywords=["Station"],
            oracle_text="When Deep Space 9 enters and at the beginning of your upkeep, exile the top four cards of your library. Put all permanent cards exiled this way onto the battlefield.\n"
            "Station (Tap another creature you control: Put charge counters equal to its power on this Spacecraft. Station only as a sorcery.)\n"
            "9+ | Creatures you control get +3/+3.")
    assert name == "Borg Incursion"
    return Card(id="incursion", name=name, type_line="Instant", is_instant=True,
        mana_cost_string="{2}{W}", converted_mana_cost=3,
        oracle_text="Create two 1/1 colorless Borg artifact creature tokens, then artifact creatures you control gain protection from the color of your choice until end of turn. (They can't be blocked, targeted, dealt damage, enchanted, or equipped by anything of that color.)")


def _put(engine, card, zone=Zone.BATTLEFIELD, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=zone)
    obj.controller_id = owner
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        obj.summoning_sick = False
        engine.state.add_to_battlefield(obj)
        engine.recompute_continuous_effects()
    else:
        engine.state.player_by_id(owner).add_to_zone(obj, zone)
    return obj


def _plain(name, type_line, oracle=""):
    creature = "Creature" in type_line
    return Card(id=name, name=name, type_line=type_line, is_creature=creature, is_land="Land" in type_line,
        power=2 if creature else None, toughness=2 if creature else None, oracle_text=oracle,
        loyalty=2 if "Planeswalker" in type_line else None, defense=2 if "Battle" in type_line else None)


@pytest.mark.parametrize("name", ["Deep Space 9", "Borg Incursion"])
def test_specs_are_fresh_valid_and_bind(name):
    first, second = specs_for(_card(name)), specs_for(_card(name))
    assert first and first[0] is not second[0] and first[0].effects[0] is not second[0].effects[0]
    for spec in first:
        spec.validate()
    engine, _, _ = game()
    obj = _put(engine, _card(name))
    assert (obj.triggered_abilities and obj.static_effects and obj.activated_abilities) if name == "Deep Space 9" else obj.spell_effects


@pytest.mark.parametrize("type_line,enters", [
    ("Artifact", True), ("Creature — Bear", True), ("Enchantment", True), ("Land", True),
    ("Planeswalker — Test", True), ("Battle — Siege", True), ("Instant", False),
    ("Sorcery", False), ("Kindred Instant — Wizard", False),
])
def test_deep_space_puts_each_permanent_card_type_into_play_and_leaves_spells_exiled(type_line, enters):
    engine, p1, _ = game()
    obj = _put(engine, _plain("Find", type_line), Zone.LIBRARY)
    ship = _put(engine, _card("Deep Space 9"), Zone.HAND)
    cast(engine, p1, ship)
    assert obj.zone == (Zone.BATTLEFIELD if enters else Zone.EXILE)
    assert not p1.has_lost  # a short library is fine: exiling is not drawing


def test_deep_space_admits_mixed_card_types_together_before_etb_triggers_resolve():
    engine, p1, _ = game()
    finds = []
    for index in range(2):
        finds.append(_put(engine, _plain(f"Observer {index}", "Creature — Bear",
            "When this creature enters, you gain life equal to the number of creatures you control."), Zone.LIBRARY))
    finds.append(_put(engine, _plain("Relic", "Artifact"), Zone.LIBRARY))
    finds.append(_put(engine, _plain("Land", "Land"), Zone.LIBRARY))
    ship = _put(engine, _card("Deep Space 9"), Zone.HAND)
    cast(engine, p1, ship)
    assert all(o.zone == Zone.BATTLEFIELD for o in finds)
    assert all(o.triggered_abilities for o in finds[:2])
    assert p1.life == 24  # each observer sees both creatures, not a partial entry
    batches = [e for e in engine.state.events_this_turn() if e.type == "EVENT_BATCH"
               and e.get("batch_of") == "ENTERS_BATTLEFIELD"]
    assert any({m.get("instance_id") for m in e.get("members", [])} == {o.instance_id for o in finds} for e in batches)


def test_deep_space_entry_choices_survive_clone_and_keep_the_entire_batch_in_exile_until_answered():
    engine, p1, _ = game()
    voice = _put(engine, Card(id="voice", name="Voice of All", type_line="Creature — Angel", is_creature=True,
        power=2, toughness=2, keywords=["Flying"], oracle_text="Flying\nAs this creature enters, choose a color.\n"
        "This creature has protection from the chosen color."), Zone.LIBRARY)
    relic = _put(engine, _plain("Relic", "Artifact"), Zone.LIBRARY)
    ship = _put(engine, _card("Deep Space 9"), Zone.HAND)
    cast(engine, p1, ship)
    assert engine.state.pending_choice["kind"] == "choose_color"
    assert voice.zone == relic.zone == Zone.EXILE
    engine = GameEngine(engine.state.clone())
    engine.resolve_pending_choice("R")
    engine.resolve_until_stable()
    voice = engine.state.find_object(voice.instance_id)
    assert voice.zone == Zone.BATTLEFIELD and voice.chosen_color == "R"
    assert engine.state.find_object(relic.instance_id).zone == Zone.BATTLEFIELD


def test_deep_space_upkeep_reads_only_the_new_pool_and_empty_library_does_nothing():
    engine, p1, p2 = game(via_steps=True)
    p1.library.clear()
    old = _put(engine, _plain("Old unrelated relic", "Artifact"), Zone.EXILE)
    spells = [_put(engine, _plain(f"Spell {i}", "Instant"), Zone.LIBRARY) for i in range(4)]
    ship = _put(engine, _card("Deep Space 9"), Zone.HAND)
    cast(engine, p1, ship)
    assert all(o.zone == Zone.EXILE for o in spells)
    fresh = _put(engine, _plain("Fresh relic", "Artifact"), Zone.LIBRARY)
    advance_to(engine, "upkeep")  # opponent's upkeep does not fire this ability
    engine.resolve_until_stable()
    assert engine.state.active_player.id == "p2" and fresh.zone == Zone.LIBRARY
    engine.advance_step()
    advance_to(engine, "upkeep")
    engine.resolve_until_stable()
    assert fresh.zone == Zone.BATTLEFIELD
    assert old.zone == Zone.EXILE and all(o.zone == Zone.EXILE for o in spells)
    assert not p1.has_lost


def test_deep_space_station_at_nine_buffs_only_your_creatures_without_becoming_a_creature():
    engine, p1, p2 = game()
    ship = _put(engine, _card("Deep Space 9"))
    donor = vanilla(engine, "p1", "Donor", 9, 9)
    mine, theirs = vanilla(engine, "p1"), vanilla(engine, "p2")
    engine.activate_ability(p1, ship, targets=[donor])
    engine.resolve_until_stable()
    assert donor.tapped and ship.counters["charge"] == 9
    assert (mine.power, mine.toughness) == (5, 5) and theirs.power == 2
    assert not ship.is_creature


def test_deep_space_entry_trigger_still_resolves_after_the_source_leaves():
    engine, p1, p2 = game()
    find = _put(engine, _plain("Relic", "Artifact"), Zone.LIBRARY)
    ship = _put(engine, _card("Deep Space 9"), Zone.HAND)
    p1.mana_pool.add("C", 9)
    engine.cast_spell(p1, ship)
    engine.rules.resolve_top_of_stack()
    engine.rules.put_triggers_on_stack()
    engine.rules.destroy(ship)
    engine.resolve_until_stable()
    assert ship in p1.graveyard and find.zone == Zone.BATTLEFIELD


def test_latest_exile_return_ignores_a_card_that_left_and_was_exiled_again():
    engine, p1, p2 = game()
    source = _put(engine, _card("Deep Space 9"))
    obj = _put(engine, _plain("Relic", "Artifact"), Zone.EXILE)
    engine.rules.context.latest_exiled_visits = [(obj, obj.zone_incarnation)]
    engine.rules.return_to_hand(obj)
    engine.rules.exile(obj)
    effect = EffectRegistry.create("put_latest_exiled_onto_battlefield", {})
    effect.source = source
    effect.apply(engine.rules.context)
    engine.resolve_until_stable()
    assert obj in p1.exile and obj not in engine.state.battlefield


def _incursion(via_steps=False):
    engine, p1, p2 = game(via_steps=via_steps)
    eligible = _put(engine, _plain("Artifact Bear", "Artifact Creature — Bear"))
    eligible.temp_keywords.add("shroud")  # a group effect must not target
    plain = vanilla(engine, "p1")
    relic = _put(engine, _plain("Relic", "Artifact"))
    enemy = _put(engine, _plain("Enemy Artifact Bear", "Artifact Creature — Bear"), owner="p2")
    spell = _put(engine, _card("Borg Incursion"), Zone.HAND)
    cast(engine, p1, spell)
    return engine, p1, p2, eligible, plain, relic, enemy


@pytest.mark.parametrize("clone", [False, True])
def test_borg_incursion_creates_tokens_then_gives_one_chosen_color_to_the_whole_untargeted_group(clone):
    engine, p1, p2, eligible, plain, relic, enemy = _incursion()
    tokens = [o for o in engine.state.battlefield if o.is_token]
    assert len(tokens) == 2
    assert all((o.power, o.toughness, o.colors) == (1, 1, set()) and o.is_artifact and o.has_subtype("Borg") for o in tokens)
    choice = engine.state.pending_choice
    assert choice["kind"] == "grant_protection_color"
    assert {o["id"] for o in choice["options"]} == {"W", "U", "B", "R", "G"}
    assert set(choice["target_ids"]) == {eligible.instance_id, *(o.instance_id for o in tokens)}
    if clone:
        engine = GameEngine(engine.state.clone())
    engine.resolve_pending_choice("R")
    engine.resolve_until_stable()
    for obj in [eligible, *tokens]:
        assert engine.state.find_object(obj.instance_id).temp_protections == {"R"}
    for obj in [plain, relic, enemy]:
        assert not engine.state.find_object(obj.instance_id).temp_protections
    assert engine.state.pending_choice is None


def test_borg_incursion_protection_prevents_damage_expires_and_does_not_cover_later_arrivals():
    engine, p1, p2, eligible, *_ = _incursion(via_steps=True)
    engine.resolve_pending_choice("R")
    engine.resolve_until_stable()
    late = _put(engine, _plain("Late Artifact Bear", "Artifact Creature — Bear"))
    red = _put(engine, Card(id="red", name="Red source", type_line="Creature", is_creature=True,
        power=2, toughness=2, mana_cost_string="{R}"), owner="p2")
    engine.rules.deal_damage(eligible, 2, source=red)
    engine.resolve_until_stable()
    assert eligible.damage_marked == 0 and not late.temp_protections
    advance_to(engine, "cleanup")
    engine.resolve_until_stable()
    assert not eligible.temp_protections


def test_borg_incursion_rejects_unoffered_colorless_and_does_not_grant_to_a_later_zone_visit():
    engine, p1, p2, eligible, *_ = _incursion()
    engine.rules.return_to_hand(eligible)
    p1.remove_from_zone(eligible, Zone.HAND)
    engine.state.add_to_battlefield(eligible)
    engine.resolve_pending_choice("colorless")
    engine.resolve_until_stable()
    assert not eligible.temp_protections
    assert all(o.temp_protections == {"W"} for o in engine.state.battlefield if o.is_token)

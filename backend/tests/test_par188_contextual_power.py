"""Contextual characteristic quantities bind once to the correct zone visit."""
import pytest

from mtg_analyzer.game import mana_abilities  # noqa: F401
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.game import creature, land, make_engine, obj_on_battlefield
from tests.test_land_animate_family import _named


@pytest.mark.parametrize("name", [
    "Chameleon Colossus", "Dying Wish", "Electrostatic Pummeler", "Elenda's Hierophant",
    "Faerie Bladecrafter", "Feral Animist", "Heroes' Bane", "Murder Investigation",
    "Spotter Thopter", "Tarox Bladewing", "Ukkima, Stalking Shadow", "Yew Spirit", "Necrosynthesis",
    "Halana and Alena, Partners", "Resilient Khenra", "Rampant Rejuvenator",
])
def test_real_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled


def _source(name):
    eng = make_engine([], [], hand=0)
    source = obj_on_battlefield(eng.state, eng, _named(name))
    bind_from_catalogue(source)
    eng.recompute_continuous_effects()
    return eng, source, eng.state.player_by_id("p1")


@pytest.mark.parametrize("name,axis", [("Chameleon Colossus", "both"), ("Feral Animist", "power")])
def test_activated_self_pump_measures_at_resolution_once_and_expires(name, axis):
    eng, source, player = _source(name)
    player.mana_pool.add_many({"G": 8, "C": 12})
    before = (source.power, source.toughness)
    eng.activate_ability(player, source, ability_index=0)
    eng.rules.add_counters(source, 2, "+1/+1")
    eng.recompute_continuous_effects()
    clone = GameEngine(eng.state.clone())
    clone.resolve_until_stable()
    changed = clone.state.find_object(source.instance_id)
    expected = before[0] + 2
    assert changed.power == expected * 2
    assert changed.toughness == before[1] + 2 + (expected if axis == "both" else 0)
    assert source.power == expected
    clone.activate_ability(clone.state.player_by_id("p1"), changed, ability_index=0)
    clone.resolve_until_stable()
    assert changed.power == expected * 4
    clone._step_cleanup()
    clone.recompute_continuous_effects()
    assert changed.power == expected


def test_heroes_bane_measures_before_adding_counters():
    eng, source, player = _source("Heroes' Bane")
    eng.rules.add_counters(source, 4, "+1/+1")
    player.mana_pool.add_many({"G": 2, "C": 2})
    eng.activate_ability(player, source, ability_index=0)
    eng.resolve_until_stable()
    assert source.counters["+1/+1"] == 8 and source.power == 8


@pytest.mark.parametrize("name", ["Murder Investigation", "Dying Wish"])
def test_attached_host_death_uses_host_lki_through_target_choice_clone(name):
    eng, aura, _ = _source(name)
    host = obj_on_battlefield(eng.state, eng, creature(power=3, toughness=6))
    aura.attached_to = host.instance_id
    host.temp_power = 3
    eng.rules.add_counters(host, 2, "+1/+1")
    eng.recompute_continuous_effects()
    assert host.power == 8
    eng.rules.destroy(host)
    eng.resolve_until_stable()
    clone = GameEngine(eng.state.clone())
    if name == "Dying Wish":
        assert clone.state.pending_choice["kind"] == "trigger_target"
        clone.resolve_pending_choice("p2")
        clone.resolve_until_stable()
        assert [p.life for p in clone.state.players] == [28, 12]
        assert [p.life for p in eng.state.players] == [20, 20]
    else:
        assert sum(o.is_token and o.card.name == "Soldier" for o in clone.state.battlefield) == 8


def test_self_death_tokens_use_departed_visit_not_returned_card():
    eng, source, _ = _source("Elenda's Hierophant")
    eng.rules.add_counters(source, 3, "+1/+1")
    eng.recompute_continuous_effects()
    eng.rules.destroy(source)
    eng.rules.put_triggers_on_stack()
    old_visit = source.zone_incarnation
    eng.rules.blink(source)
    source.temp_power = 6
    eng.recompute_continuous_effects()
    assert source.zone == Zone.BATTLEFIELD and source.zone_incarnation > old_visit
    assert source.power == 7
    clone = GameEngine(eng.state.clone())
    clone.resolve_until_stable()
    assert sum(o.is_token and "Vampire" in o.card.type_line for o in clone.state.battlefield) == 4
    assert not any(o.is_token for o in eng.state.battlefield)


def test_multiplayer_death_drain_gains_power_only_once():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", []), ("p3", "C", [])], starting_hand=0, starting_life=20)
    source = obj_on_battlefield(eng.state, eng, _named("Faerie Bladecrafter"))
    bind_from_catalogue(source)
    source.temp_power = 3
    eng.recompute_continuous_effects()
    expected = source.power
    eng.rules.destroy(source)
    eng.rules.put_triggers_on_stack()
    clone = GameEngine(eng.state.clone())
    clone.resolve_until_stable()
    assert [p.life for p in clone.state.players] == [20 + expected, 20 - expected, 20 - expected]


@pytest.mark.parametrize("value", [5, -2])
def test_contextual_self_pump_uses_zero_for_negative_result(value):
    eng, source, _ = _source("Yew Spirit")
    source.temp_power = value - int(source.card.power)
    eng.recompute_continuous_effects()
    before = (source.power, source.toughness)
    specs = parse_effect_body("~ gets +x/+x until end of turn, where x is its power",
                              reading=ClauseReading(self_subject=True))
    build_effects(specs, source)[0].apply(GameContext(eng.state, eng.rules))
    eng.recompute_continuous_effects()
    assert (source.power, source.toughness) == tuple(n + max(0, value) for n in before)


@pytest.mark.parametrize("body,reading,referent", [
    ("~ gets +x/+x until end of turn, where x is its power", ClauseReading(group_subject=True), "source"),
    ("it gets +x/+x until end of turn, where x is its power", ClauseReading(group_subject=True), "trigger_subject"),
    ("target creature gets +x/+x until end of turn, where x is its power", ClauseReading(self_subject=True), "target"),
])
def test_explicit_body_subject_and_trigger_subject_are_distinct(body, reading, referent):
    specs = parse_effect_body(body, reading=reading)
    if specs[0].type == "trigger_subject_referent":
        specs = [type(specs[0])(**specs[0].params["effects"][0])]
        referent = "target"  # wrapper passes the firing creature as the inner target
    assert specs[0].type == "bind" and specs[0].params["amount"]["of"] == referent


@pytest.mark.parametrize("body", [
    "draw x cards, where x is its power",
    "~ gets +x/+x until end of turn, where x is its defense",
    "~ gets +x/+x until end of turn, where x is its power and draw 2 cards",
])
def test_ambiguous_or_unsupported_quantities_fail_closed(body):
    assert parse_effect_body(body) is None


def test_counter_then_power_measurement_is_not_hoisted():
    eng, source, _ = _source("Yew Spirit")
    body = "put a +1/+1 counter on ~, then ~ gets +x/+x until end of turn, where x is its power"
    specs = parse_effect_body(body, reading=ClauseReading(self_subject=True))
    before = source.power
    for effect in build_effects(specs, source):
        effect.apply(GameContext(eng.state, eng.rules))
    eng.recompute_continuous_effects()
    assert source.power == 2 * (before + 1)


def test_named_that_object_requires_an_antecedent():
    body = "create x 1/1 white soldier creature tokens, where x is that artifact's power"
    assert parse_effect_body(body, reading=ClauseReading(self_subject=True)) is None


def test_named_creature_still_names_group_even_when_source_gets_the_pump():
    body = "~ gets +x/+x until end of turn, where x is that creature's power"
    specs = parse_effect_body(body, reading=ClauseReading(group_subject=True))
    assert specs[0].params["amount"]["of"] == "trigger_subject"


def test_explicit_self_after_target_does_not_measure_previous_creature():
    body = "target creature gets +1/+1 until end of turn. ~ gets +x/+x until end of turn, where x is its power"
    specs = parse_effect_body(body, reading=ClauseReading(self_subject=True))
    assert specs[-1].params["amount"]["of"] == "source"


def test_explicit_self_counters_after_target_measure_source():
    eng, source, _ = _source("Yew Spirit")
    other = obj_on_battlefield(eng.state, eng, creature(power=8, toughness=8))
    body = "target creature gets +1/+1 until end of turn. put x +1/+1 counters on ~, where x is its power"
    specs = parse_effect_body(body, reading=ClauseReading(self_subject=True))
    assert specs[-1].params["amount"]["of"] == "source"
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned
    _apply_effects_partitioned(build_effects(specs, source), GameContext(eng.state, eng.rules), [other], None, source=source)
    eng.recompute_continuous_effects()
    assert source.power == 6 and other.power == 9


def test_spotter_scry_uses_resolution_power_and_preserves_open_choice_on_clone():
    eng, source, player = _source("Spotter Thopter")
    for i in range(12):
        player.library.append(GameObject(land(str(i)), owner_id="p1", zone=Zone.LIBRARY))
    eng.rules._place_trigger(source.triggered_abilities[0])
    eng.rules.add_counters(source, 2, "+1/+1")
    eng.recompute_continuous_effects()
    expected = source.power
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "scry"
    assert len(eng.state.pending_choice["options"]) == expected + 1
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice("decline")
    clone.resolve_pending_choice("decline")
    assert clone.state.pending_choice is None
    assert eng.state.pending_choice["kind"] == "scry"


def test_ukkima_leave_uses_old_visit_and_life_gain_is_not_damage_dealt():
    from mtg_analyzer.game.effects.core import ReplacementEffect
    from mtg_analyzer.models.game.events import EventType
    eng, source, player = _source("Ukkima, Stalking Shadow")
    source.temp_power = 4
    eng.recompute_continuous_effects()
    assert source.power == 6
    eng.rules.blink(source)
    eng.rules.add_counters(source, 7, "+1/+1")
    eng.rules.put_triggers_on_stack()
    assert eng.state.pending_choice["kind"] == "trigger_target"
    clone = GameEngine(eng.state.clone())
    protector = obj_on_battlefield(clone.state, clone, creature("Preventer"))
    protector.replacement_effects.append(ReplacementEffect(EventType.DAMAGE, lambda e, c: None))
    clone.resolve_pending_choice("p2")
    clone.resolve_until_stable()
    assert [p.life for p in clone.state.players] == [26, 20]


def test_optional_attached_death_tokens_preserve_power_snapshot_through_clone():
    eng = make_engine([], [], hand=0)
    card = Card(id="optional-death", name="Optional Death", type_line="Enchantment — Aura",
                oracle_text="Enchant creature\nWhen enchanted creature dies, you may create X 1/1 white Soldier creature tokens, where X is its power.")
    assert parse_oracle(card).modeled
    aura = obj_on_battlefield(eng.state, eng, card)
    bind_from_catalogue(aura)
    host = obj_on_battlefield(eng.state, eng, creature(power=3, toughness=6))
    aura.attached_to = host.instance_id
    host.temp_power = 4
    eng.recompute_continuous_effects()
    eng.rules.destroy(host)
    eng.resolve_until_stable()
    assert eng.state.pending_choice is not None
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice("do")
    clone.resolve_until_stable()
    assert sum(o.is_token for o in clone.state.battlefield) == 7


def test_spotter_measures_layer_set_base_power_instead_of_printed_power():
    eng, source, player = _source("Spotter Thopter")
    from mtg_analyzer.parser.oracle.spec import EffectSpec
    build_effects([EffectSpec("grant_until", {"self_subject": True, "static": {
        "type": "type_change", "params": {"power": 2, "toughness": 3},
    }})], source)[0].apply(GameContext(eng.state, eng.rules))
    for i in range(10):
        player.library.append(GameObject(land(str(i)), owner_id="p1", zone=Zone.LIBRARY))
    eng.recompute_continuous_effects()
    assert source.power == 2
    eng.rules._place_trigger(source.triggered_abilities[0])
    eng.resolve_until_stable()
    assert len(eng.state.pending_choice["options"]) == 3


def test_contextual_animation_keeps_negative_base_pt_setting():
    eng = make_engine([], [], hand=0)
    source = obj_on_battlefield(eng.state, eng, land())
    # A resolving ability can measure a noncreature source's signed power
    # through a current creature type-change grant.
    from mtg_analyzer.parser.oracle.spec import EffectSpec
    build_effects([EffectSpec("grant_until", {"self_subject": True, "static": {
        "type": "type_change", "params": {"add_types": ["creature"], "power": -2, "toughness": 4},
    }})], source)[0].apply(GameContext(eng.state, eng.rules))
    eng.recompute_continuous_effects()
    specs = parse_effect_body("~ becomes an x/x creature until end of turn, where x is its power. it's still a land",
                              reading=ClauseReading(self_subject=True))
    assert "minimum" not in specs[0].params["amount"]
    build_effects(specs, source)[0].apply(GameContext(eng.state, eng.rules))
    eng.recompute_continuous_effects()
    assert source.power == source.toughness == -2


@pytest.mark.parametrize("name", ["Fiendlash", "Lothlórien Blade"])
@pytest.mark.parametrize("change", ["reattach", "blink"])
def test_attached_damage_measures_exact_event_host_and_host_is_dealer(name, change):
    from mtg_analyzer.models.game.events import EventType, GameEvent
    eng, equipment, player = _source(name)
    host = obj_on_battlefield(eng.state, eng, creature("Lifelink Host", power=3, toughness=7))
    host.temp_keywords.add("lifelink")
    host.temp_keywords.add("deathtouch")
    other = obj_on_battlefield(eng.state, eng, creature("Later Host", power=9, toughness=9))
    enemy = obj_on_battlefield(eng.state, eng, creature("Enemy", power=1, toughness=20), controller="p2")
    equipment.attached_to = host.instance_id
    eng.recompute_continuous_effects()
    if name == "Fiendlash":
        eng.rules.deal_damage(host, 1, source=equipment)
    else:
        host.combat_defender = {"kind": "player", "id": "p2"}
        eng.state.fire_event(GameEvent(EventType.ATTACKS, instance_id=host.instance_id, controller_id="p1", defending_player_id="p2"))
    eng.rules.put_triggers_on_stack()
    assert eng.state.pending_choice["kind"] == "trigger_target"
    host.temp_power = 2
    eng.recompute_continuous_effects()
    if change == "reattach":
        equipment.attached_to = other.instance_id
        eng.recompute_continuous_effects()
        expected = host.power
    else:
        expected = host.power
        old_visit = host.zone_incarnation
        eng.rules.blink(host)
        eng.rules.add_counters(host, 8, "+1/+1")
        eng.recompute_continuous_effects()
        assert host.zone_incarnation != old_visit and host.power != expected
    clone = GameEngine(eng.state.clone())
    target = "p2" if name == "Fiendlash" else str(enemy.instance_id)
    clone.resolve_pending_choice(target)
    clone.resolve_until_stable()
    assert clone.state.player_by_id("p1").life == 20 + expected
    if name == "Fiendlash":
        assert clone.state.player_by_id("p2").life == 20 - expected
    else:
        assert clone.state.find_object(enemy.instance_id).zone == Zone.GRAVEYARD


def test_shriveling_rot_keeps_measurement_inside_future_death_trigger():
    assert parse_oracle(_named("Shriveling Rot")).modeled


def test_departed_token_dealer_and_power_survive_sba_removal_and_clone():
    eng, equipment, _ = _source("Fiendlash")
    host = obj_on_battlefield(eng.state, eng, creature("Token Host", power=3, toughness=7))
    host.is_token = True
    host.temp_keywords.add("lifelink")
    equipment.attached_to = host.instance_id
    eng.recompute_continuous_effects()
    assert host.power == 5
    eng.rules.deal_damage(host, 1, source=equipment)
    eng.rules.put_triggers_on_stack()
    assert eng.state.pending_choice["kind"] == "trigger_target"
    eng.rules.destroy(host)
    # Finish announcement without auto-resolving the queued trigger, then
    # take the SBA pass that removes the departed token before resolution.
    eng.rules.resolve_choice("p2")
    eng.rules.check_state_based_actions()
    assert eng.state.find_object(host.instance_id) is None
    assert eng.state.stack
    clone = GameEngine(eng.state.clone())
    clone.resolve_until_stable()
    assert [p.life for p in clone.state.players] == [25, 15]


def test_explicit_source_counters_and_haste_tail_share_target_and_survive_clone():
    eng, source, _ = _source("Halana and Alena, Partners")
    target = obj_on_battlefield(eng.state, eng, creature(power=1, toughness=2))
    eng.rules._place_trigger(source.triggered_abilities[0], targets=[target])
    eng.rules.add_counters(source, 2, "+1/+1")
    eng.recompute_continuous_effects()
    expected = source.power
    clone = GameEngine(eng.state.clone())
    clone.resolve_until_stable()
    changed = clone.state.find_object(target.instance_id)
    assert changed.counters["+1/+1"] == expected
    assert "haste" in changed.granted_keywords
    assert source.counters["+1/+1"] == 2


@pytest.mark.parametrize("accept", [True, False])
def test_explicit_source_optional_targeted_pump(accept):
    from mtg_analyzer.models.game.events import EventType, GameEvent
    eng, source, _ = _source("Resilient Khenra")
    target = obj_on_battlefield(eng.state, eng, creature(power=1, toughness=2))
    source.temp_power = 4
    eng.recompute_continuous_effects()
    assert source.power == 6
    eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=source.instance_id, controller_id="p1"))
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "trigger_target"
    assert all(o["id"] != "decline" for o in eng.state.pending_choice["options"])
    eng.rules.resolve_choice(str(target.instance_id))
    assert eng.state.stack
    eng.rules.blink(source)
    eng.recompute_continuous_effects()
    assert source.power == 2
    clone = GameEngine(eng.state.clone())
    clone.resolve_until_stable()
    assert clone.state.pending_choice["kind"] == "composite_optional"
    paused = GameEngine(clone.state.clone())
    paused.resolve_pending_choice("yes" if accept else "decline")
    paused.resolve_until_stable()
    assert paused.state.find_object(target.instance_id).power == (7 if accept else 1)
    assert target.power == 1


def test_optional_pump_required_target_triggers_ward_before_resolution_choice():
    from mtg_analyzer.models.game.events import EventType, GameEvent
    eng, source, player = _source("Resilient Khenra")
    target = obj_on_battlefield(eng.state, eng, creature("Ward Target", power=1, toughness=5), controller="p2")
    target.parametric_keywords["ward"] = {"cost": "{1}"}
    player.mana_pool.add_many({"C": 1})
    eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=source.instance_id, controller_id="p1"))
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "trigger_target"
    assert all(o["id"] != "decline" for o in eng.state.pending_choice["options"])
    eng.rules.resolve_choice(str(target.instance_id))
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "ward"
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice("pay")
    clone.resolve_until_stable()
    assert clone.state.pending_choice["kind"] == "composite_optional"
    assert clone.state.player_by_id("p1").mana_pool.total() == 0
    clone.resolve_pending_choice("decline")
    clone.resolve_until_stable()
    assert clone.state.find_object(target.instance_id).power == 1


def test_legacy_source_power_pump_clamps_negative_x_without_becoming_a_debuff():
    eng, source, _ = _source("Resilient Khenra")
    target = obj_on_battlefield(eng.state, eng, creature(power=3, toughness=4))
    source.temp_power = -5
    eng.recompute_continuous_effects()
    assert source.power == -3
    specs = parse_effect_body("target creature gets +x/+x until end of turn, where x is ~'s power")
    build_effects(specs, source)[0].apply(GameContext(eng.state, eng.rules), [target])
    eng.recompute_continuous_effects()
    assert (target.power, target.toughness) == (3, 4)


@pytest.mark.parametrize("selector", ["source_power", "source_toughness"])
@pytest.mark.parametrize("value", [4, -2])
@pytest.mark.parametrize("negative", [False, True])
def test_legacy_source_stat_pump_clamps_x_before_printed_sign(selector, value, negative):
    from mtg_analyzer.parser.oracle.spec import EffectSpec
    eng, source, _ = _source("Yew Spirit")
    target = obj_on_battlefield(eng.state, eng, creature(power=10, toughness=10))
    if selector == "source_power":
        source.temp_power = value - int(source.card.power)
    else:
        source.temp_toughness = value - int(source.card.toughness)
    eng.recompute_continuous_effects()
    specs = [EffectSpec("pump", {"target_kind": "creature", "amount_from_count_selector": selector,
                                  "amount_from_count_selector_negative": negative})]
    build_effects(specs, source)[0].apply(GameContext(eng.state, eng.rules), [target])
    eng.recompute_continuous_effects()
    expected = 10 + max(0, value) * (-1 if negative else 1)
    assert target.power == target.toughness == expected


@pytest.mark.parametrize("referent", ["its power", "that creature's power"])
@pytest.mark.parametrize("value", [3, -2])
@pytest.mark.parametrize("axis", ["0", "x"])
def test_target_characteristic_pump_floors_negative_x_and_preserves_axes(referent, value, axis):
    eng, source, _ = _source("Yew Spirit")
    target = obj_on_battlefield(eng.state, eng, creature(power=value, toughness=5))
    eng.recompute_continuous_effects()
    body = f"target creature gets +x/+{axis} until end of turn, where x is {referent}"
    specs = parse_effect_body(body)
    effect = build_effects(specs, source)[0]
    assert len(effect.target_specs) == 1
    effect.apply(GameContext(eng.state, eng.rules), [target])
    eng.recompute_continuous_effects()
    assert (target.power, target.toughness) == (value + max(0, value), 5 + (max(0, value) if axis == "x" else 0))


def test_inline_source_search_quantity_survives_departure_and_clone():
    eng, source, player = _source("Rampant Rejuvenator")
    for i in range(4):
        player.library.append(GameObject(land(str(i)), owner_id="p1", zone=Zone.LIBRARY))
    eng.rules.add_counters(source, 2, "+1/+1")
    eng.recompute_continuous_effects()
    eng.rules.destroy(source)
    eng.rules.put_triggers_on_stack()
    clone = GameEngine(eng.state.clone())
    clone.resolve_until_stable()
    assert clone.state.pending_choice["kind"] == "search"
    for _ in range(2):
        choice = clone.state.pending_choice
        option = next(o for o in choice["options"] if o["id"] != "decline")
        clone.resolve_pending_choice(option["id"])
    clone.resolve_until_stable()
    assert sum(o.is_land for o in clone.state.battlefield) == 2


@pytest.mark.parametrize("name", ["Emergent Woodwurm", "Fatal Frenzy", "Ravenous Gigantotherium", "Rip, Spawn Hunter", "Self-Destruct"])
def test_independent_body_grammar_stays_fail_closed(name):
    assert not parse_oracle(_named(name)).modeled

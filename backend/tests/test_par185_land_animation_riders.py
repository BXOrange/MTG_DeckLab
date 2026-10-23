"""PAR-185 — land-animation riders: "it's still a land" / "that's still a land" on the animate rows, the
Zendikon-style "enchanted land is a N/N … creature" static and the mass "all lands you control become …" row.

RULE 205.1b: still-a-land animation retains prior types and subtypes, so the
reminder sentence is parsed and discarded.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import mana_abilities  # noqa: F401  (registers mana-ability bindings like the sibling tests)
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

from tests.support.game import land, make_engine, obj_on_battlefield
from tests.test_land_animate_family import _named


def test_self_animation_with_land_reminder_parses():
    specs = parse_effect_body(
        "~ becomes a 1/1 blinkmoth artifact creature with flying until end of turn. it's still a land."
    )
    assert specs is not None and len(specs) == 1
    params = specs[0].params
    assert params["duration"] == "end_of_turn"
    assert params["static"]["params"]["add_subtypes"] == ["Blinkmoth"]
    assert params["static"]["params"]["add_types"] == ["creature", "artifact"]


def test_leading_duration_self_animation_takes_keywords():
    specs = parse_effect_body(
        "until end of turn, ~ becomes a 2/2 black and green elemental creature with deathtouch. it's still a land."
    )
    assert specs is not None
    assert specs[0].params["extra_statics"][-1] == {"type": "grant_keyword", "params": {"keywords": ["deathtouch"]}}


def test_target_relative_clause_reminder_without_duration_is_permanent():
    specs = parse_effect_body("target land becomes a 3/3 creature that's still a land.")
    assert specs is not None and specs[0].params["duration"] == "rest_of_game"


def test_unknown_creature_word_stays_unclaimed():
    assert parse_effect_body("~ becomes a 1/1 notatype creature until end of turn. it's still a land.") is None


def test_enchanted_land_static_parses():
    specs = static_effect_specs("enchanted land is a 4/2 red beast creature with trample. it's still a land.")
    assert specs is not None
    assert [s.type for s in specs] == ["type_change", "color", "grant_keyword"]
    assert specs[0].params["affects"] == "attached_permanent"
    assert (specs[0].params["power"], specs[0].params["toughness"]) == (4, 2)


def test_group_land_static_parses_and_other_subjects_do_not():
    specs = static_effect_specs("forests you control are 1/1 green elf creatures that are still lands.")
    assert specs is not None and specs[0].params["affects"] == "lands_you_control_of_type_forest"
    assert static_effect_specs("enchanted creature is a 4/2 red beast creature. it's still a land.") is None


def test_mass_land_animation_is_locked_group():
    specs = parse_effect_body("all lands you control become 1/1 creatures until end of turn. they're still lands.")
    assert specs is not None
    assert specs[0].params["lock_group"] is True
    assert specs[0].params["static"]["params"]["affects"] == "lands_you_control"


def test_real_cards_are_modeled():
    for name in ("Blinkmoth Nexus", "Faerie Conclave", "Crusher Zendikon", "Animate Land",
                 "Crawling Barrens", "Embodiment of Insight", "Embodiment of Fury",
                 "Faceless Haven", "Lavaclaw Reaches", "Mishra's Factory"):
        assert parse_oracle(_named(name)).modeled is True, name
    assert parse_oracle(_named("Deadly Complication")).modeled


@pytest.mark.parametrize("body", [
    "it becomes a 0/0 elemental creature with haste that's still a land",
    "they become 3/3 green creatures with haste that are still lands",
])
def test_previous_animation_requires_a_referent(body):
    from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading
    assert parse_effect_body(body) is None
    specs = parse_effect_body(body, reading=ClauseReading(previous_subject=True))
    assert specs and specs[0].params["previous_subject"] is True


def test_counter_then_optional_self_animation_keeps_the_choice():
    specs = parse_effect_body(
        "put 2 +1/+1 counters on ~. then you may have it become a 0/0 elemental creature "
        "until end of turn. it's still a land."
    )
    assert specs and [s.type for s in specs] == ["add_counters", "optional"]
    grant = specs[1].params["effects"][0]
    assert grant["type"] == "grant_until" and grant["params"]["self_subject"] is True


def test_quoted_animation_fails_closed_for_unknown_ability():
    assert parse_effect_body(
        'until end of turn, ~ becomes a 2/2 creature with "do an impossible thing." it\'s still a land.'
    ) is None


def test_attached_animation_and_source_duration_are_independent_axes():
    specs = parse_effect_body("enchanted forest becomes a 4/4 green spirit creature until end of turn. it's still a land")
    assert specs and specs[0].params["lock_group"] is True
    assert specs[0].params["static"]["params"]["affects"] == "attached_permanent"
    specs = parse_effect_body("until end of turn, enchanted swamp becomes a 2/2 black spirit creature with \"{b}: ~ gets +1/+1 until end of turn.\" it's still a land")
    assert specs and specs[0].params["extra_statics"][-1]["type"] == "grant_activated_ability"
    specs = parse_effect_body("target forest becomes a 4/5 green treefolk creature for as long as ~ remains on the battlefield. it's still a land")
    assert specs and specs[0].params["duration"] == "for_as_long_as"
    assert specs[0].params["condition"] == {"kind": "source_on_battlefield"}
    assert parse_oracle(_named("Awakener Druid")).modeled


def test_animation_rejects_empty_grant_and_mismatched_retention():
    assert parse_effect_body("~ becomes a 2/2 creature with  until end of turn") is None
    assert parse_effect_body("target artifact becomes a 2/2 creature that's still a land") is None
    assert parse_effect_body("target artifact becomes a 2/2 creature. it's still a land") is None
    assert parse_effect_body("until end of turn, target artifact becomes a 2/2 creature. it's still a land") is None


def test_multi_target_animation_uses_one_optional_target_group():
    specs = parse_effect_body(
        "up to 3 target lands you control each become 2/2 warrior creatures until end of turn. they're still lands."
    )
    assert specs and len(specs) == 1
    assert specs[0].params["target_kind"] == "land_you_control"
    assert specs[0].params["count"] == 3 and specs[0].params["optional"] is True
    assert parse_oracle(_named("Anthousa, Setessan Hero")).modeled


def test_blinkmoth_nexus_animates_itself_and_stays_a_land():
    eng = make_engine([_named("Blinkmoth Nexus")], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"C": 1})
    nexus = obj_on_battlefield(eng.state, eng, _named("Blinkmoth Nexus"), controller="p1")
    bind_from_catalogue(nexus)
    eng.recompute_continuous_effects()
    assert nexus.is_creature is False

    # The mana ability is not in the activated-ability index space (Kamahl's animation is index 0 too).
    eng.activate_ability(p1, nexus, ability_index=0)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()

    assert nexus.is_creature is True
    assert nexus.is_land is True
    assert (nexus.power, nexus.toughness) == (1, 1)
    assert "flying" in nexus.granted_keywords


def test_lavaclaw_reaches_grants_an_activatable_pump_that_expires():
    from mtg_analyzer.game import durations
    eng = make_engine([_named("Lavaclaw Reaches")], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    reaches = obj_on_battlefield(eng.state, eng, _named("Lavaclaw Reaches"), controller="p1")
    bind_from_catalogue(reaches)
    p1.mana_pool.add_many({"B": 1, "R": 1, "C": 4})
    eng.activate_ability(p1, reaches, ability_index=0)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert reaches.is_land and reaches.is_creature
    assert (reaches.power, reaches.toughness) == (2, 2)
    eng.activate_ability(p1, reaches, ability_index=1, x=3)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert (reaches.power, reaches.toughness) == (5, 2)
    durations.sweep(eng.state, "cleanup")
    eng.recompute_continuous_effects()
    assert not reaches.is_creature
    assert len(reaches.activated_abilities) == 1


def test_mass_animation_locks_existing_lands_and_preserves_other_types():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import GameContext
    from mtg_analyzer.models.cards.card import Card
    eng = make_engine([], [], hand=0)
    artifact_land = Card(id="artifact-land", name="Artifact Forest", type_line="Artifact Land — Forest", is_land=True)
    forest = obj_on_battlefield(eng.state, eng, artifact_land, controller="p1")
    source = obj_on_battlefield(eng.state, eng, land("Source", "Island"), controller="p1")
    specs = parse_effect_body("all lands you control become 1/1 creatures until end of turn. they're still lands.")
    build_effects(specs, source)[0].apply(GameContext(eng.state, eng.rules))
    newcomer = obj_on_battlefield(eng.state, eng, land(), controller="p1")
    eng.recompute_continuous_effects()
    assert forest.is_land and forest.is_artifact and forest.is_creature
    assert (forest.power, forest.toughness) == (1, 1)
    assert not newcomer.is_creature


def test_zendikon_animates_only_its_enchanted_land():
    eng = make_engine([], [], hand=0)
    host = obj_on_battlefield(eng.state, eng, land(), controller="p1")
    other = obj_on_battlefield(eng.state, eng, land("Island", "Island"), controller="p1")
    aura = obj_on_battlefield(eng.state, eng, _named("Crusher Zendikon"), controller="p1")
    aura.attached_to = host.instance_id
    bind_from_catalogue(aura)
    eng.recompute_continuous_effects()
    assert host.is_land and host.is_creature
    assert (host.power, host.toughness) == (4, 2)
    assert "trample" in host.granted_keywords
    assert not other.is_creature


def _awakener_druid_grant():
    from mtg_analyzer.game.effects.core import GameContext
    eng = make_engine([], [], hand=0)
    druid = obj_on_battlefield(eng.state, eng, _named("Awakener Druid"), controller="p1")
    forest = obj_on_battlefield(eng.state, eng, land(), controller="p1")
    bind_from_catalogue(druid)
    context = GameContext(eng.state, eng.rules)
    context.resolving_source_incarnation = druid.zone_incarnation
    grant = druid.triggered_abilities[0].effects[0]
    return eng, druid, forest, context, grant


def test_awakener_druid_old_grant_cannot_start_after_source_blinks():
    eng, druid, forest, context, grant = _awakener_druid_grant()
    original_visit = druid.zone_incarnation
    eng.rules.blink(druid)
    assert druid.zone_incarnation != original_visit
    # Resolve only the original trigger, whose source visit was captured
    # before the blink; the returned Druid's new ETB is a separate trigger.
    grant.apply(context, [forest])
    eng.recompute_continuous_effects()
    assert forest.is_land and not forest.is_creature
    assert not eng.state.floating_statics


def test_active_awakener_druid_grant_ends_during_source_blink():
    eng, druid, forest, context, grant = _awakener_druid_grant()
    grant.apply(context, [forest])
    assert forest.is_creature and (forest.power, forest.toughness) == (4, 5)
    eng.rules.blink(druid)
    eng.recompute_continuous_effects()
    assert forest.is_land and not forest.is_creature
    assert not eng.state.floating_statics


def test_blinkmoth_old_activation_does_not_animate_returned_source():
    eng = make_engine([_named("Blinkmoth Nexus")], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    player = eng.state.active_player
    player.mana_pool.add_many({"C": 1})
    nexus = obj_on_battlefield(eng.state, eng, _named("Blinkmoth Nexus"), controller="p1")
    bind_from_catalogue(nexus)
    eng.activate_ability(player, nexus, ability_index=0)
    eng.rules.blink(nexus)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert nexus.is_land and not nexus.is_creature
    assert not eng.state.floating_statics

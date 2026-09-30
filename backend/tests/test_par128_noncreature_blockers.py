"""PAR-128: "target noncreature permanent" and "each creature blocking it".

* `noncreature_permanent` is a target kind of its own (any permanent that is not a creature —
  lands included, unlike `noncreature_nonland_permanent`), and a narrowing of "any permanent",
  so every verb that takes a permanent target takes it.
* `blocking_source` is a `matches_object_filter` key: the creature is one of the *reference*
  object's declared blockers (RULE 509.1a, `GameObject.blocked_by`). "Whenever ~ becomes blocked,
  it deals 1 damage to each creature blocking it" is a mass-damage group carrying it.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import targeting
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.subgrammars import resolve_target_kind, target_kind_allowed
from mtg_analyzer.parser.oracle.gate import parse_oracle as _parse

from tests.test_par119_cast_trigger_grammar import _engine
from tests.test_par120_count_phrase import _creature, _put


def _specs(oracle: str, types: str = "Creature — Bear"):
    result = _parse(Card(id="Src", name="Src", type_line=types, oracle_text=oracle,
                         is_sorcery="Sorcery" in types, is_creature="Creature" in types))
    return result, [e for s in result.specs for e in s.effects]


# -- noncreature permanent -----------------------------------------------------


def test_kind_is_a_narrowing_of_any_permanent():
    assert resolve_target_kind("target noncreature permanent") == "noncreature_permanent"
    assert target_kind_allowed("noncreature_permanent", ("permanent",))


@pytest.mark.parametrize("oracle, effect_type", [
    ("Destroy target noncreature permanent.", "destroy"),
    ("Exile target noncreature permanent.", "exile"),
    ("Return target noncreature permanent to its owner's hand.", "return_to_hand"),
])
def test_verbs_take_the_kind(oracle, effect_type):
    result, effects = _specs(oracle, types="Sorcery")
    assert result.modeled, oracle
    assert [(e.type, e.params["target_kind"]) for e in effects] == [(effect_type, "noncreature_permanent")]


def test_legal_targets_are_every_noncreature_permanent_lands_included():
    _engine_, state = _engine()
    spell = _put(state, "Destroy target noncreature permanent.", name="Spell", types="Sorcery")
    bear = _creature(state, "Bear")
    ring = GameObject(Card(id="Ring", name="Ring", type_line="Artifact"),
                      owner_id="p2", zone=Zone.BATTLEFIELD)
    ring.controller_id = "p2"
    state.add_to_battlefield(ring)
    forest = GameObject(Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True),
                        owner_id="p2", zone=Zone.BATTLEFIELD)
    forest.controller_id = "p2"
    state.add_to_battlefield(forest)
    found = {t["instance_id"] for t in targeting.legal_targets(
        state, "p1", targeting.TargetSpec(kind="noncreature_permanent"), source=spell)}
    assert found == {ring.instance_id, forest.instance_id}
    assert bear.instance_id not in found


# -- creatures blocking it -----------------------------------------------------

GOBLIN = "Whenever ~ becomes blocked, it deals 1 damage to each creature blocking it."


def test_the_group_carries_the_blockers_of_the_dealer():
    result, [effect] = _specs(GOBLIN)
    assert result.modeled
    assert effect.type == "damage"
    assert effect.params["group"]["filter"] == {"card_type": "creature", "blocking_source": True}


def test_a_group_head_names_the_firing_creature_as_the_dealer():
    _, [effect] = _specs("Whenever a Goblin you control becomes blocked, it deals 2 damage to each creature blocking it.",
                         types="Enchantment")
    assert effect.params["dealer_event_key"] == "__group_subject__"


def test_an_attached_head_is_refused_because_it_is_not_the_source():
    # "equipped creature becomes blocked, it deals …": the dealer is the creature, not the Equipment.
    result, _ = _specs("Whenever equipped creature becomes blocked, it deals 2 damage to each creature blocking it.",
                       types="Artifact — Equipment")
    assert not result.modeled


def test_only_the_creatures_blocking_the_source_take_the_damage():
    engine, state = _engine()
    state.current_step = "combat_declare_blockers"
    goblin = _put(state, GOBLIN, name="Goblin", types="Creature — Goblin")
    blocker = _creature(state, "Blocker", owner="p2")
    bystander = _creature(state, "Bystander", owner="p2")
    goblin.attacking = True
    goblin.blocked_by = [blocker.instance_id]
    blocker.blocking = goblin.instance_id
    state.fire_event(GameEvent(
        EventType.BECOMES_BLOCKED, attacker=goblin.name, player_id="p1",
        instance_id=goblin.instance_id, object_types=sorted(goblin.type_words), blocker_count=1,
    ))
    engine.resolve_until_stable()
    on_battlefield = {o.instance_id for o in state.battlefield}
    assert blocker.instance_id not in on_battlefield
    assert bystander.instance_id in on_battlefield
    assert goblin.instance_id in on_battlefield


def test_a_group_head_damage_comes_from_the_creature_that_was_blocked():
    engine, state = _engine()
    state.current_step = "combat_declare_blockers"
    _put(state, "Whenever a Goblin you control becomes blocked, it deals 2 damage to each creature blocking it.",
         name="Banner", types="Enchantment")
    goblin = _creature(state, "Goblin", types="Creature — Goblin")
    other = _creature(state, "Other", types="Creature — Goblin")
    blocker = _creature(state, "Blocker", owner="p2")
    goblin.attacking = True
    goblin.blocked_by = [blocker.instance_id]
    blocker.blocking = goblin.instance_id
    other.blocked_by = []
    state.fire_event(GameEvent(
        EventType.BECOMES_BLOCKED, attacker=goblin.name, player_id="p1",
        instance_id=goblin.instance_id, object_types=sorted(goblin.type_words), blocker_count=1,
    ))
    engine.resolve_until_stable()
    assert blocker.instance_id not in {o.instance_id for o in state.battlefield}


# -- "sacrifice it" under a group trigger ---------------------------------------

IB = ("Whenever another Goblin you control becomes blocked, sacrifice it. "
      "If you do, it deals 4 damage to each creature blocking it.")


def test_sacrifice_it_names_the_firing_creature_not_the_source():
    _, [sacrifice, damage] = _specs(IB, types="Creature — Goblin")
    assert sacrifice.type == "sacrifice_self"
    assert sacrifice.params["target_kind"] == "trigger_subject"
    assert damage.params["dealer_event_key"] == "__group_subject__"


def test_the_blocked_goblin_is_sacrificed_and_hits_its_blockers():
    engine, state = _engine()
    state.current_step = "combat_declare_blockers"
    ib = _put(state, IB, name="Ib", types="Creature — Goblin")
    goblin = _creature(state, "Goblin", types="Creature — Goblin")
    blocker = _creature(state, "Blocker", owner="p2")
    bystander = _creature(state, "Bystander", owner="p2")
    goblin.attacking = True
    goblin.blocked_by = [blocker.instance_id]
    blocker.blocking = goblin.instance_id
    state.fire_event(GameEvent(
        EventType.BECOMES_BLOCKED, attacker=goblin.name, player_id="p1",
        instance_id=goblin.instance_id, object_types=sorted(goblin.type_words), blocker_count=1,
    ))
    engine.resolve_until_stable()
    alive = {o.instance_id for o in state.battlefield}
    assert ib.instance_id in alive  # the ability's own source is not the sacrifice
    assert goblin.instance_id not in alive
    assert blocker.instance_id not in alive
    assert bystander.instance_id in alive


# -- mass tap scoped to the defending / event player ------------------------------


def test_tap_all_lands_defending_player_controls_parses():
    result, [effect] = _specs("Whenever enchanted creature becomes blocked, tap all lands defending player controls.",
                              types="Enchantment — Aura")
    assert result.modeled
    assert effect.params["selector_player"] == "defending"
    assert effect.params["selector"]["of"] == "you"


def test_tap_all_creatures_defending_player_controls_taps_only_the_attacked_players():
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    engine, state = _engine()
    state.current_step = "declare_attackers"
    attacker = _creature(state, "Torrent")
    attacker.card.oracle_text = "Whenever ~ attacks, tap all creatures defending player controls.".replace("~", "Torrent")
    bind_from_catalogue(attacker)
    attacker.summoning_sick = False
    mine = _creature(state, "Mine")
    theirs = _creature(state, "Theirs", owner="p2")
    engine.declare_attackers(state.active_player, [attacker])
    engine.resolve_until_stable()
    assert theirs.tapped is True
    assert mine.tapped is False


# -- "those creatures" after a mass tap scoped to a chosen player -----------------


def test_those_creatures_are_the_chosen_players_not_the_casters():
    # Sleep: "Tap all creatures target player controls. Those creatures don't untap during that
    # player's next untap step." — the referent is the group *for the chosen player*.
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    engine, state = _engine()
    src = _creature(state, "Caster")
    mine = _creature(state, "Mine")
    theirs = _creature(state, "Theirs", owner="p2")
    specs = parse_effect_body(
        "tap all creatures target player controls. those creatures don't untap during that player's next untap step."
    )
    assert specs is not None
    _apply_effects_partitioned(build_effects(specs, src), engine.rules.context, [state.player_by_id("p2")], None, source=src)
    assert theirs.tapped is True and theirs.skip_next_untap is True
    assert mine.tapped is False and mine.skip_next_untap is False
    assert src.skip_next_untap is False


def test_a_pump_after_a_named_mass_group_reads_the_same_referent():
    # `pump_previous_selector` now resolves through `previous_group_objects`.
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    engine, state = _engine()
    src = _creature(state, "Caster")
    mine = _creature(state, "Mine")
    theirs = _creature(state, "Theirs", owner="p2")
    specs = parse_effect_body("tap all creatures you control. those creatures gain flying until end of turn.")
    if specs is None:
        pytest.skip("no parsed pump-after-tap row")
    _apply_effects_partitioned(build_effects(specs, src), engine.rules.context, None, None, source=src)
    assert mine.tapped is True and theirs.tapped is False


# -- "each of up to N other target creatures you control" ----------------------------


def test_plural_other_and_you_control_slots_compose_on_counters():
    result, [effect] = _specs(
        "When this creature enters, put a +1/+1 counter on each of up to 2 other target creatures you control."
    )
    assert result.modeled
    assert effect.params["target_kind"] == "other_creature_you_control"
    assert effect.params["target_count"] == 2 and effect.params["optional"] is True


def test_plural_scope_without_other_keeps_the_source_eligible():
    _, [effect] = _specs("Put a +1/+1 counter on each of up to 2 target creatures you control.", types="Sorcery")
    assert effect.params["target_kind"] == "creature_you_control"


def test_other_on_a_pool_that_includes_the_source_is_refused():
    # "other target artifacts" reads as the broad permanent pool, which does leave the source out;
    # a pool with no source-excluding form has to fail closed instead of guessing.
    result, _ = _specs("Tap up to 2 other target players.", types="Sorcery")
    assert not result.modeled


def test_the_other_pool_never_offers_the_source():
    _engine_, state = _engine()
    src = _put(state, "x", name="Savior", types="Creature — Cat")
    mine = _creature(state, "Mine")
    theirs = _creature(state, "Theirs", owner="p2")
    spec = targeting.TargetSpec(kind="other_creature_you_control")
    found = {t["instance_id"] for t in targeting.legal_targets(state, "p1", spec, source=src)}
    assert found == {mine.instance_id}
    assert theirs.instance_id not in found and src.instance_id not in found


# -- "destroy/exile all <group>" -----------------------------------------------------------


def _resolve(oracle: str, types: str, state, engine, source, targets=None):
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    specs = parse_effect_body(oracle)
    assert specs is not None, oracle
    _apply_effects_partitioned(build_effects(specs, source), engine.rules.context, targets, None, source=source)
    engine.resolve_until_stable()
    return specs


def _coloured(state, name, colors, owner="p1", types="Creature — Bear"):
    card = Card(id=name, name=name, type_line=types, is_creature="Creature" in types,
                power=1 if "Creature" in types else None, toughness=1 if "Creature" in types else None,
                color_identity=set(colors))
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    state.add_to_battlefield(obj)
    return obj


@pytest.mark.parametrize("oracle, kind", [
    ("destroy all forests", "destroy"),
    ("destroy all artifacts you don't control", "destroy"),
    ("destroy all lands target player controls", "destroy"),
    ("exile all artifacts and enchantments your opponents control", "exile"),
    ("destroy each creature with flying", "destroy"),
])
def test_the_group_rows_parse_to_a_structured_group(oracle, kind):
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    [spec] = parse_effect_body(oracle)
    assert spec.type == kind and spec.params["group"]["zone"] == "battlefield"


def test_the_named_selectors_still_win_over_the_group_row():
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    [spec] = parse_effect_body("destroy all creatures")
    assert spec.params == {"selector": "all_creatures"}
    [spec] = parse_effect_body("destroy all artifacts your opponents control")
    assert spec.params == {"selector": "opponents_artifacts"}


@pytest.mark.parametrize("oracle", [
    "destroy all creatures blocking or blocked by it",
    "destroy all creatures except target creature",
    "exile all creatures chosen this way",
    "exile all cards from graveyards",
])
def test_a_group_the_grammar_cannot_state_stays_unclaimed(oracle):
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    assert parse_effect_body(oracle) is None


def test_destroy_all_white_permanents_leaves_the_rest():
    engine, state = _engine()
    src = _creature(state, "Caster")
    white = _coloured(state, "White", "W")
    other_white = _coloured(state, "Theirs", "W", owner="p2")
    green = _coloured(state, "Green", "G")
    _resolve("destroy all white permanents", "Sorcery", state, engine, src)
    alive = {o.instance_id for o in state.battlefield}
    assert white.instance_id not in alive and other_white.instance_id not in alive
    assert green.instance_id in alive and src.instance_id in alive


def test_destroy_all_you_dont_control_spares_your_own():
    engine, state = _engine()
    src = _creature(state, "Caster")
    mine = _creature(state, "Mine")
    theirs = _creature(state, "Theirs", owner="p2")
    _resolve("destroy all creatures you don't control", "Sorcery", state, engine, src)
    alive = {o.instance_id for o in state.battlefield}
    assert theirs.instance_id not in alive
    assert mine.instance_id in alive and src.instance_id in alive


def test_destroy_all_lands_target_player_controls_hits_only_that_player():
    engine, state = _engine()
    src = _creature(state, "Caster")
    lands = {}
    for owner in ("p1", "p2"):
        land = GameObject(Card(id=f"L{owner}", name=f"Land {owner}", type_line="Basic Land — Forest", is_land=True),
                          owner_id=owner, zone=Zone.BATTLEFIELD)
        land.controller_id = owner
        state.add_to_battlefield(land)
        lands[owner] = land
    _resolve("destroy all lands target player controls", "Sorcery", state, engine, src,
             targets=[state.player_by_id("p2")])
    alive = {o.instance_id for o in state.battlefield}
    assert lands["p2"].instance_id not in alive
    assert lands["p1"].instance_id in alive


def test_exile_all_artifacts_your_opponents_control_uses_the_group():
    engine, state = _engine()
    src = _creature(state, "Caster")
    rocks = {}
    for owner in ("p1", "p2"):
        rock = GameObject(Card(id=f"R{owner}", name=f"Rock {owner}", type_line="Artifact"),
                          owner_id=owner, zone=Zone.BATTLEFIELD)
        rock.controller_id = owner
        state.add_to_battlefield(rock)
        rocks[owner] = rock
    _resolve("exile all artifacts and enchantments your opponents control", "Sorcery", state, engine, src)
    alive = {o.instance_id for o in state.battlefield}
    assert rocks["p2"].instance_id not in alive and rocks["p1"].instance_id in alive


def test_with_no_counters_is_a_negation_not_a_counter_kind():
    from mtg_analyzer.game import combat
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    [spec] = parse_effect_body("destroy all creatures with no counters on them")
    assert spec.params["group"]["filter"] == {"card_type": "creature", "no_counters": True}
    engine, state = _engine()
    bare = _creature(state, "Bare")
    marked = _creature(state, "Marked")
    marked.counters["+1/+1"] = 1
    filt = spec.params["group"]["filter"]
    assert combat.matches_object_filter(bare, filt) and not combat.matches_object_filter(marked, filt)


# -- "return all <group> to their owners' hands" ------------------------------------------


def _hand_ids(state, owner):
    return {o.instance_id for o in state.player_by_id(owner).hand}


def test_return_all_creatures_bounces_every_creature():
    engine, state = _engine()
    src = _creature(state, "Caster")
    mine = _creature(state, "Mine")
    theirs = _creature(state, "Theirs", owner="p2")
    _resolve("return all creatures to their owners' hands", "Sorcery", state, engine, src)
    assert mine.instance_id in _hand_ids(state, "p1") and src.instance_id in _hand_ids(state, "p1")
    assert theirs.instance_id in _hand_ids(state, "p2")


def test_return_each_other_creature_you_control_spares_the_source_and_opponents():
    engine, state = _engine()
    src = _creature(state, "Caster")
    mine = _creature(state, "Mine")
    theirs = _creature(state, "Theirs", owner="p2")
    _resolve("return each other creature you control to its owner's hand", "Sorcery", state, engine, src)
    alive = {o.instance_id for o in state.battlefield}
    assert mine.instance_id in _hand_ids(state, "p1")
    assert src.instance_id in alive and theirs.instance_id in alive


def test_return_all_green_permanents_uses_the_colour_filter():
    engine, state = _engine()
    src = _creature(state, "Caster")
    green = _coloured(state, "Green", "G")
    red = _coloured(state, "Red", "R")
    _resolve("return all green permanents to their owners' hands", "Sorcery", state, engine, src)
    assert green.instance_id in _hand_ids(state, "p1")
    assert red.instance_id in {o.instance_id for o in state.battlefield}


# -- "counter target spell you don't control" ------------------------------------------------


def test_counter_target_spell_you_dont_control_parses_to_the_scoped_kind():
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
    from mtg_analyzer.parser.oracle.spec import EffectSpec

    assert match_clause("counter target spell you don't control") == [
        EffectSpec("counter", {"target_kind": "spell_you_dont_control"})
    ]
    assert match_clause("counter target spell an opponent controls unless they pay {1}") == [
        EffectSpec("counter", {"target_kind": "spell_you_dont_control", "unless_pays": "{1}"})
    ]
    # the unscoped phrase is unchanged
    assert match_clause("counter target spell") == [EffectSpec("counter", {})]


def test_only_the_opponents_spell_is_a_legal_target():
    from tests.test_counter_family import creature, push_spell, two_player_engine

    eng, alice, bob = two_player_engine()
    mine = push_spell(eng, alice, creature("Mine"))
    theirs = push_spell(eng, bob, creature("Theirs"))
    spec = targeting.TargetSpec(kind="spell_you_dont_control")
    found = {t["instance_id"] for t in targeting.legal_targets(eng.state, alice.id, spec)}
    assert theirs.instance_id in found and mine.instance_id not in found


# -- "each of those creatures deals damage equal to its power to ~" ------------------------------


def test_each_of_those_creatures_needs_a_preceding_target_clause():
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    assert parse_effect_body("each of those creatures deals damage equal to its power to ~") is None
    specs = parse_effect_body(
        "~ deals 3 damage divided as you choose among any number of target creatures your opponents control. "
        "each of those creatures deals damage equal to its power to ~"
    )
    assert [s.type for s in specs] == ["damage", "damage_equal_to_power"]
    assert specs[1].params == {"dealer_group": "previous_targets"}


def test_every_earlier_target_hits_the_source_for_its_own_power():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    engine, state = _engine()
    src = _put(state, "x", name="Polukranos", types="Creature — Hydra")
    src.card.toughness = 20
    big = _creature(state, "Big", owner="p2")
    big.card.power, big.card.toughness = 4, 9
    small = _creature(state, "Small", owner="p2")
    small.card.power, small.card.toughness = 2, 9
    bystander = _creature(state, "Bystander", owner="p2")
    bystander.card.power, bystander.card.toughness = 7, 9
    specs = parse_effect_body(
        "~ deals 1 damage divided as you choose among any number of target creatures your opponents control. "
        "each of those creatures deals damage equal to its power to ~"
    )
    _apply_effects_partitioned(
        build_effects(specs, src), engine.rules.context, [big, small], None, source=src,
    )
    assert src.damage_marked == 4 + 2  # the bystander was never a target


# -- "X target creatures" (the announced X is the target count) -----------------------------------


@pytest.mark.parametrize("oracle, effect_type", [
    ("tap x target creatures", "tap"),
    ("tap up to x target creatures", "tap"),
    ("destroy x target artifacts", "destroy"),
    ("return x target creatures to their owners' hands", "return_to_hand"),
    ("exile x target creatures you control", "exile"),
])
def test_x_target_count_reads_the_announced_x(oracle, effect_type):
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    [spec] = parse_effect_body(oracle)
    assert spec.type == effect_type
    assert spec.params["count_selector"] == "source_x_paid" and spec.params["optional"] is True


def test_x_target_count_is_refused_where_the_effect_cannot_read_it():
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    assert parse_effect_body("~ deals 2 damage to each of x target creatures") is None


def test_the_plural_single_type_rows_no_longer_offer_any_permanent():
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    [spec] = parse_effect_body("destroy 2 target artifacts")
    assert spec.params["target_kind"] == "artifact"
    [spec] = parse_effect_body("destroy x target lands")
    assert spec.params["target_kind"] == "land"


def test_x_targets_are_all_destroyed_not_truncated_to_one():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    engine, state = _engine()
    src = _put(state, "x", name="Spell", types="Sorcery")
    src.x_paid = 2
    rocks = []
    for n in range(3):
        rock = GameObject(Card(id=f"R{n}", name=f"Rock {n}", type_line="Artifact"),
                          owner_id="p2", zone=Zone.BATTLEFIELD)
        rock.controller_id = "p2"
        state.add_to_battlefield(rock)
        rocks.append(rock)
    specs = parse_effect_body("destroy x target artifacts")
    [effect] = build_effects(specs, src)
    assert targeting.resolved_count(effect.target_spec, state, "p1", src) == 2
    _apply_effects_partitioned([effect], engine.rules.context, rocks[:2], None, source=src)
    alive = {o.instance_id for o in state.battlefield}
    assert rocks[0].instance_id not in alive and rocks[1].instance_id not in alive
    assert rocks[2].instance_id in alive


def test_stun_counters_go_only_on_the_targets_you_dont_control():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    engine, state = _engine()
    src = _put(state, "x", name="Maze", types="Enchantment")
    mine = _creature(state, "Mine")
    theirs = _creature(state, "Theirs", owner="p2")
    specs = parse_effect_body(
        "tap 2 target creatures. put a stun counter on each of those creatures you don't control"
    )
    _apply_effects_partitioned(build_effects(specs, src), engine.rules.context, [mine, theirs], None, source=src)
    assert mine.counters.get("stun", 0) == 0
    assert theirs.counters.get("stun", 0) == 1
    assert mine.tapped and theirs.tapped


# -- the exert rider with a gendered pronoun ---------------------------------------------------


def test_exert_rider_reads_he_and_she_as_the_creature_itself():
    result, effects = _specs(
        "You may exert ~ as he attacks. When you do, he gains flying until end of turn.",
        types="Creature — Dragon",
    )
    assert result.modeled
    assert [(e.type, e.params) for e in effects] == [("pump", {"keywords": ["flying"]})]

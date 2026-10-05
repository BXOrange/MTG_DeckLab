"""PAR-135 — a named counter on a target: the kind is an open axis, the reserved list is the guard.

`_NAMED_COUNTER_KINDS` was a closed list of the tracker words printed so far, so "put a stun counter
on target creature" (24+ solo cards), "put a shield counter on …" and every next set's "feather"/
"bloodstain" needed a row. The kind is now `[a-z]+` minus `_RESERVED_COUNTER_KINDS` — the names the
engine keys off. `stun` (RULE 122.1c, `set_tapped`) already had its replacement; `shield` (the same
rule, `deal_damage`/`destroy`) got it here, since claiming a counter the engine ignores would be a
card that parses and does nothing. Asymmetric P/T counters ("+0/+1") used to be read as +1/+1.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import mtg_analyzer.game as game_package
from mtg_analyzer.game import continuous
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.handlers import _RESERVED_COUNTER_KINDS, match_clause
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def _engine():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0)
    return engine, engine.state


def _bf(state, card, owner):
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    state.add_to_battlefield(obj)
    return obj


def _bear(state, name, owner, power=2, toughness=2):
    return _bf(state, Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
                           power=power, toughness=toughness), owner)


def _modeled(name, type_line, text):
    # `Card.is_instant`/`is_sorcery` are not derived from the type line.
    result = parse_oracle(Card(id=name, name=name, type_line=type_line, oracle_text=text,
                               is_instant="Instant" in type_line, is_sorcery="Sorcery" in type_line))
    assert result.modeled, result.unclaimed


# -- the open kind axis ---------------------------------------------------------


@pytest.mark.parametrize("kind", ["stun", "shield", "feather", "bloodstain", "velocity", "flying", "first strike"])
def test_any_non_reserved_kind_parses_on_a_target(kind):
    [spec] = match_clause(f"put a {kind} counter on target creature")
    assert spec.type == "add_counters" and spec.params["kind"] == kind
    assert spec.params["target_kind"] == "creature"


def test_count_and_controller_scope_ride_along():
    [spec] = match_clause("put 3 stun counters on target creature an opponent controls")
    assert spec.params == {"count": 3, "kind": "stun", "target_kind": "creature_you_dont_control"}


@pytest.mark.parametrize("kind", list(_RESERVED_COUNTER_KINDS))
def test_reserved_kinds_stay_unclaimed(kind):
    assert match_clause(f"put a {kind} counter on target creature") is None
    assert match_clause(f"put a {kind} counter on ~") is None


def test_the_kind_axis_reaches_every_sibling_row():
    assert match_clause("put an impostor counter on each creature you control") is not None
    assert match_clause("put a stun counter on a creature you control") is not None
    assert match_clause("remove a feather counter from ~") is not None
    assert match_clause("put a +1/+1 counter and a shield counter on target creature") is not None


def test_a_non_counter_phrase_is_not_a_kind():
    assert match_clause("put a card on target creature") is None
    assert match_clause("put a counter on target creature") is None


def _reserved_literals_read_by_the_engine() -> set[str]:
    """Every counter-kind literal `game/` reads off ``counters`` — the readers a generic bump can't feed."""
    reader = re.compile(r"""counters(?:\.get\(|\[)["']([a-z][a-z ]*)["']""")
    found: set[str] = set()
    for path in Path(game_package.__file__).parent.rglob("*.py"):
        if "card_catalogue" in path.parts:
            continue
        found.update(reader.findall(path.read_text(encoding="utf-8")))
    return found


#: Kinds `game/` reads that a generic ``add_counters`` bump feeds *completely*: the P/T pair, the two
#: replacement counters the engine enforces, and `charge` (`mana_abilities` reads the count itself).
_GENERICALLY_FED = {"stun", "shield", "charge"}
#: `counters.get("kind")`/`["count"]` read an *ability spec's* own "counters" dict, not a permanent's.
_SPEC_KEYS = {"kind", "count"}


def test_every_kind_the_engine_reads_is_reserved_or_generically_fed():
    unaccounted = _reserved_literals_read_by_the_engine() - set(_RESERVED_COUNTER_KINDS) - _GENERICALLY_FED - _SPEC_KEYS
    assert not unaccounted, (
        f"game/ now reads counter kind(s) {sorted(unaccounted)} by name; either a generic "
        "`add_counters` feeds them completely (add to _GENERICALLY_FED) or they belong in "
        "handlers._RESERVED_COUNTER_KINDS so the parser stops claiming them"
    )


# -- stun ---------------------------------------------------------------------


def test_tap_and_put_three_stun_counters_parses_with_a_count():
    specs = parse_effect_body("tap target creature an opponent controls and put 3 stun counters on it")
    assert [s.type for s in specs] == ["tap", "add_counters"]
    assert specs[1].params == {"count": 3, "kind": "stun", "previous_subject": True}


def test_stun_counters_hold_a_creature_tapped_through_untap_steps():
    engine, state = _engine()
    src = _bear(state, "src", "p1")
    victim = _bear(state, "victim", "p2")
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned

    specs = parse_effect_body("tap target creature and put 3 stun counters on it")
    _apply_effects_partitioned(build_effects(specs, src), engine.rules.context, [victim], None, source=src)
    assert victim.tapped and victim.counters["stun"] == 3
    for expected_left in (2, 1, 0):
        engine.rules.set_tapped(victim, False)  # the untap step's own choke point
        assert victim.tapped and victim.counters.get("stun", 0) == expected_left
    engine.rules.set_tapped(victim, False)
    assert not victim.tapped


def test_real_stun_cards_are_modeled():
    _modeled("Freeze in Place", "Sorcery",
             "Tap target creature an opponent controls and put three stun counters on it. Scry 2.")
    _modeled("Crimestopper Sprite", "Creature — Faerie Detective",
             "Flash\nFlying\nWhen Crimestopper Sprite enters, tap target creature. If evidence was "
             "collected, put a stun counter on it.")


# -- shield counters (RULE 122.1c) ----------------------------------------------


def test_shield_counter_prevents_damage_and_is_removed():
    engine, state = _engine()
    target, source = _bear(state, "target", "p1", 2, 3), _bear(state, "source", "p2")
    target.counters["shield"] = 1
    engine.rules.deal_damage(target, 5, source)
    assert target.damage_marked == 0 and not target.counters.get("shield")
    engine.rules.deal_damage(target, 2, source)
    assert target.damage_marked == 2  # the counter was spent; the next hit lands


def test_one_shield_counter_absorbs_a_whole_damage_event_and_several_stack():
    engine, state = _engine()
    target, source = _bear(state, "target", "p1", 2, 9), _bear(state, "source", "p2")
    target.counters["shield"] = 2
    engine.rules.deal_damage(target, 1, source)
    engine.rules.deal_damage(target, 8, source)
    assert target.damage_marked == 0 and not target.counters.get("shield")


def test_shield_counter_replaces_destruction_by_an_effect():
    engine, state = _engine()
    target = _bear(state, "target", "p1")
    target.counters["shield"] = 1
    engine.rules.destroy(target)
    assert target in state.battlefield and not target.counters.get("shield")
    engine.rules.destroy(target)
    assert target not in state.battlefield


def test_shield_counter_beats_cant_be_regenerated():
    engine, state = _engine()
    target = _bear(state, "target", "p1")
    target.counters["shield"] = 1
    engine.rules.destroy(target, can_be_regenerated=False)
    assert target in state.battlefield and not target.counters.get("shield")


def test_shield_counter_does_not_guard_the_lethal_damage_state_based_action():
    # RULE 122.1c protects against destruction "as the result of an effect" — 704.5g is not one.
    engine, state = _engine()
    target = _bear(state, "target", "p1", 2, 2)
    target.damage_marked = 2
    target.counters["shield"] = 1
    engine.rules.check_state_based_actions()
    assert target not in state.battlefield


def test_shield_counter_protects_a_planeswalker_from_damage():
    engine, state = _engine()
    walker = _bf(state, Card(id="pw", name="Walker", type_line="Legendary Planeswalker — Test",
                             loyalty=4), "p1")
    walker.counters["loyalty"] = 4
    walker.counters["shield"] = 1
    engine.rules.deal_damage(walker, 3, _bear(state, "source", "p2"))
    assert walker.counters["loyalty"] == 4 and not walker.counters.get("shield")


def test_real_shield_cards_are_modeled():
    _modeled("Boon of Safety", "Instant", "Put a shield counter on target creature.")
    _modeled("Brokers Veteran", "Creature — Human Soldier",
             "When Brokers Veteran dies, put a shield counter on target creature you control.")


# -- asymmetric P/T counters ----------------------------------------------------


def test_asymmetric_counter_is_its_own_kind_not_a_plus_one_counter():
    [spec] = match_clause("put a +0/+1 counter on target creature")
    assert spec.params == {"count": 1, "kind": "+0/+1", "target_kind": "creature"}
    [spec] = match_clause("put 2 -0/-1 counters on target creature")
    assert spec.params["kind"] == "-0/-1" and spec.params["count"] == 2


def test_symmetric_counters_keep_their_old_reading():
    [spec] = match_clause("put a +2/+2 counter on target creature")
    assert spec.params["kind"] == "+1/+1" and spec.params["count"] == 2
    [spec] = match_clause("put a −1/−1 counter on target creature")
    assert spec.params["kind"] == "-1/-1"


def test_layer_seven_adds_each_asymmetric_counters_own_delta():
    engine, state = _engine()
    bear = _bear(state, "bear", "p1", 2, 2)
    bear.counters["+0/+1"] = 2
    bear.counters["-0/-2"] = 1
    continuous.recompute(state)
    assert (bear.power, bear.toughness) == (2, 2 + 2 - 2)
    bear.counters["+1/+2"] = 1
    continuous.recompute(state)
    assert (bear.power, bear.toughness) == (3, 4)


def test_coral_reef_and_shield_sphere_are_modeled():
    _modeled("Coral Reef", "Enchantment",
             "Coral Reef enters with four polyp counters on it.\nSacrifice an Island: Put two polyp "
             "counters on Coral Reef.\n{U}, Tap an untapped blue creature you control, Remove a polyp "
             "counter from Coral Reef: Put a +0/+1 counter on target creature.")


# -- "it" after a targeting clause is that pick, not the source ------------------


def test_if_its_tapped_after_a_target_reads_the_target():
    specs = parse_effect_body("tap target creature. if it's tapped, draw a card")
    assert specs[-1].condition == {"kind": "source_tapped", "of": "previous_target"}


def test_shackle_slinger_stuns_a_tapped_target_and_taps_an_untapped_one():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned

    body = ("choose target creature an opponent controls. if it's tapped, put a stun counter on it. "
            "otherwise, tap it")
    for start_tapped in (True, False):
        engine, state = _engine()
        slinger = _bear(state, "slinger", "p1")
        victim = _bear(state, "victim", "p2")
        victim.tapped = start_tapped
        specs = parse_effect_body(body)
        _apply_effects_partitioned(build_effects(specs, slinger), engine.rules.context, [victim], None,
                                   source=slinger)
        engine.resolve_until_stable()
        assert not slinger.tapped and not slinger.counters.get("stun")
        assert victim.tapped
        assert victim.counters.get("stun", 0) == (1 if start_tapped else 0)


# -- "any target that isn't a <subtype>" ------------------------------------------


def test_isnt_a_subtype_tail_narrows_any_target():
    [spec] = match_clause("it deals that much damage to any target that isn't a dinosaur", ) or parse_effect_body(
        "it deals that much damage to any target that isn't a dinosaur", group_subject=True)
    assert spec.params["target_kind"] == "any"
    assert spec.params["creature_filter"] == {"without_subtype": "Dinosaur"}


def test_isnt_a_commander_and_an_unknown_word():
    [spec] = parse_effect_body("~ deals damage equal to that spell's mana value to any target that isn't a commander",
                               self_subject=True)
    assert spec.params["creature_filter"] == {"is_commander": False}
    assert match_clause("~ deals 3 damage to any target that isn't a zzyzx") is None
    # a pool the filter can't narrow stays unclaimed rather than losing the filter
    assert match_clause("~ deals 3 damage to target player that isn't a dinosaur") is None


def test_any_target_isnt_a_dinosaur_leaves_players_and_other_creatures_legal():
    from mtg_analyzer.game import targeting
    from mtg_analyzer.game.binding.core import build_effects

    engine, state = _engine()
    src = _bf(state, Card(id="s", name="Src", type_line="Creature — Dinosaur", is_creature=True,
                          power=2, toughness=2), "p1")
    dino = _bf(state, Card(id="d", name="Dino", type_line="Creature — Dinosaur", is_creature=True,
                           power=2, toughness=2), "p2")
    bear = _bear(state, "bear", "p2")
    specs = parse_effect_body("it deals that much damage to any target that isn't a dinosaur", group_subject=True)
    [effect] = build_effects(specs, src)
    [spec] = effect.target_specs
    offered = targeting.legal_targets(state, "p1", spec, source=src)
    names = {o["name"] for o in offered if "instance_id" in o}
    assert "Dino" not in names and "bear" in names
    assert {o["player_id"] for o in offered if "player_id" in o} == {"p1", "p2"}


def test_lozhan_style_commander_exclusion():
    from mtg_analyzer.game import targeting
    from mtg_analyzer.game.binding.core import build_effects

    engine, state = _engine()
    src = _bear(state, "src", "p1")
    cmdr, plain = _bear(state, "cmdr", "p2"), _bear(state, "plain", "p2")
    cmdr.is_commander = True
    specs = parse_effect_body("~ deals damage equal to that spell's mana value to any target that isn't a commander",
                              self_subject=True)
    [effect] = build_effects(specs, src)
    names = {o.get("name") for o in targeting.legal_targets(state, "p1", effect.target_specs[0], source=src)}
    assert "cmdr" not in names and "plain" in names


# -- "Do this only once each turn" ----------------------------------------------------


def _life_card(text):
    return Card(id="lg", name="Life Giver", type_line="Creature — Human", is_creature=True, power=1,
                toughness=1, oracle_text=text)


def test_action_limit_is_a_gated_seq_with_a_stamp_not_a_trigger_limit():
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    from mtg_analyzer.game.effects.game_status import ConditionalEffect

    engine, state = _engine()
    obj = _bf(state, _life_card("Whenever you scry, you may gain 1 life. Do this only once each turn."), "p1")
    bind_from_catalogue(obj)
    [ability] = obj.triggered_abilities
    assert ability.action_key is not None and ability.once_per_turn is False
    [gate] = ability.effects
    assert isinstance(gate, ConditionalEffect) and gate.condition["kind"] == "action_unused_this_turn"
    assert [s["type"] for s in gate.inner.inner_specs] == ["action_stamp", "gain_life"]


def test_the_stamp_sits_where_a_nested_optional_action_is_accepted():
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    engine, state = _engine()
    gremlin = _bf(state, _life_card("Whenever you scry, you may discard a card. If you do, draw a card. "
                                    "Do this only once each turn."), "p1")
    bind_from_catalogue(gremlin)
    [ability] = gremlin.triggered_abilities
    [node] = ability.effects[0].inner.inner_specs
    assert node["type"] == "pay_cost_then" and node["params"]["effects"][0]["type"] == "action_stamp"
    legolas = _bf(state, _life_card("Whenever you scry, if ~ is tapped, you may untap it. "
                                    "Do this only once each turn."), "p1")
    bind_from_catalogue(legolas)
    [node] = legolas.triggered_abilities[0].effects[0].inner.inner_specs
    assert node["type"] == "optional" and node["params"]["effects"][0]["type"] == "action_stamp"


def test_the_action_happens_once_a_turn_and_a_declined_firing_does_not_use_it_up():
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    from mtg_analyzer.models.game.events import EventType, GameEvent

    engine, state = _engine()
    p1 = state.players[0]
    obj = _bf(state, _life_card("Whenever you scry, you may gain 1 life. Do this only once each turn."), "p1")
    bind_from_catalogue(obj)
    engine.begin_turn()
    state.current_step = "main1"

    def scry(answer):
        before = p1.life
        state.fire_event(GameEvent(EventType.SCRY, player_id="p1"))
        engine.resolve_until_stable()  # places the trigger, pausing at its "you may"
        if state.pending_choice is not None:
            engine.rules.resolve_choice(answer)
            engine.resolve_until_stable()
        return p1.life - before

    assert scry("decline") == 0          # declined: still available
    assert scry("do") == 1               # performed
    assert scry("do") == 0               # already done this turn — no prompt, nothing happens
    assert state.pending_choice is None
    engine.begin_turn()
    engine.begin_turn()
    state.current_step = "main1"
    assert scry("do") == 1               # a new turn


def test_declining_an_optional_action_inside_the_body_does_not_use_the_turn_up():
    # Legolas, Counter of Kills: the "you may" is *inside* the body, so the limit is recorded on accepting it.
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    from mtg_analyzer.models.game.events import EventType, GameEvent

    engine, state = _engine()
    obj = _bf(state, _life_card("Whenever you scry, if ~ is tapped, you may untap it. "
                                "Do this only once each turn."), "p1")
    bind_from_catalogue(obj)
    engine.begin_turn()
    state.current_step = "main1"

    def scry(answer):
        state.fire_event(GameEvent(EventType.SCRY, player_id="p1"))
        engine.resolve_until_stable()
        if state.pending_choice is not None:
            options = {o["id"] for o in state.pending_choice["options"]}
            engine.rules.resolve_choice("yes" if answer == "do" and "yes" in options else answer)
            engine.resolve_until_stable()

    obj.tapped = True
    scry("decline")
    assert obj.tapped                        # declined, nothing spent
    scry("do")
    assert not obj.tapped                    # performed once
    obj.tapped = True
    scry("do")
    assert obj.tapped                        # the second performance this turn is refused


def test_two_firings_already_on_the_stack_still_act_only_once():
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    engine, state = _engine()
    p1 = state.players[0]
    obj = _bf(state, _life_card("Whenever you scry, gain 2 life. Do this only once each turn."), "p1")
    bind_from_catalogue(obj)
    [ability] = obj.triggered_abilities
    before = p1.life
    ability.apply(engine.rules.context)
    ability.apply(engine.rules.context)
    assert p1.life - before == 2
    engine.begin_turn()
    ability.apply(engine.rules.context)
    assert p1.life - before == 4


def test_two_limited_abilities_on_one_permanent_do_not_share_a_turn():
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    engine, state = _engine()
    p1 = state.players[0]
    obj = _bf(state, _life_card("Whenever you scry, gain 2 life. Do this only once each turn.\n"
                                "Whenever you surveil, gain 5 life. Do this only once each turn."), "p1")
    bind_from_catalogue(obj)
    first, second = obj.triggered_abilities
    before = p1.life
    first.apply(engine.rules.context)
    second.apply(engine.rules.context)
    assert p1.life - before == 7


def test_an_unplaceable_action_limit_fails_closed():
    from mtg_analyzer.parser.oracle.spec import EffectSpec, fold_action_limit

    buried = [EffectSpec("if_else", {"then": [{"type": "action_once_per_turn_marker", "params": {}}]})]
    assert fold_action_limit(buried, "action_once_per_turn_marker", "k") is None


def test_action_limit_on_a_spell_fails_closed():
    result = parse_oracle(Card(id="x", name="X", type_line="Instant", is_instant=True,
                               oracle_text="Draw a card. Do this only once each turn."))
    assert not result.modeled


def test_ondu_spiritdancer_and_irreverent_gremlin_are_modeled():
    _modeled("Ondu Spiritdancer", "Creature — Human Cleric",
             "First strike\nWhenever an enchantment you control enters, you may create a token that's a copy "
             "of it. Do this only once each turn.")
    _modeled("Irreverent Gremlin", "Creature — Gremlin",
             "Whenever another creature you control with power 2 or less enters, you may discard a card. "
             "If you do, draw a card. Do this only once each turn.")


# -- power-only doubling --------------------------------------------------------------


def test_double_power_only_leaves_toughness_alone():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned

    engine, state = _engine()
    src = _bear(state, "src", "p1")
    victim = _bear(state, "victim", "p2", 3, 4)
    specs = parse_effect_body("double target creature's power until end of turn")
    assert specs[0].params["self_multiplier_stat"] == "power"
    _apply_effects_partitioned(build_effects(specs, src), engine.rules.context, [victim], None, source=src)
    assert (victim.power, victim.toughness) == (6, 4)


def test_double_power_and_toughness_is_unchanged():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned

    engine, state = _engine()
    src = _bear(state, "src", "p1")
    victim = _bear(state, "victim", "p2", 3, 4)
    specs = parse_effect_body("double the power and toughness of target creature until end of turn")
    assert "self_multiplier_stat" not in specs[0].params
    _apply_effects_partitioned(build_effects(specs, src), engine.rules.context, [victim], None, source=src)
    assert (victim.power, victim.toughness) == (6, 8)


def test_death_kiss_doubles_the_attacking_creature_not_the_source():
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    from mtg_analyzer.models.game.events import EventType, GameEvent

    engine, state = _engine()
    kiss = _bf(state, Card(id="dk", name="Death Kiss", type_line="Enchantment", oracle_text=(
        "Whenever a creature an opponent controls attacks one of your opponents, double its power "
        "until end of turn.")), "p1")
    bind_from_catalogue(kiss)
    specs = parse_effect_body("double its power until end of turn", group_subject=True)
    assert specs[0].params["trigger_subject"] is True and specs[0].params["self_multiplier_stat"] == "power"


def test_double_its_power_on_an_equipment_trigger_reads_the_host():
    result = parse_oracle(Card(id="th", name="Two-Handed Axe", type_line="Artifact — Equipment", oracle_text=(
        "Whenever equipped creature attacks, double its power until end of turn.\nEquip {2}")))
    assert result.modeled, result.unclaimed
    [trigger] = [s for s in result.specs if s.ability_kind == "triggered"]
    assert trigger.effects[0].params["target_kind"] == "attached_permanent"


# -- additive colours -----------------------------------------------------------------


def test_becomes_a_black_zombie_adds_the_colour_and_the_subtype():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned

    engine, state = _engine()
    src = _bear(state, "src", "p1")
    green = _bf(state, Card(id="g", name="Green", type_line="Creature — Elf", is_creature=True, power=1,
                            toughness=1, color_identity={"G"}), "p1")
    specs = parse_effect_body("target creature becomes a black zombie in addition to its other colors and types "
                              "until end of turn")
    assert specs[0].params["extra_statics"] == [{"type": "color", "params": {"colors": ["B"], "set": False}}]
    _apply_effects_partitioned(build_effects(specs, src), engine.rules.context, [green], None, source=src)
    assert set(green.colors) == {"G", "B"} and "Zombie" in green._added_subtypes


def test_a_colour_word_without_the_additive_tail_stays_unclaimed():
    # "becomes a black Zombie in addition to its other types" replaces the colour — not modelled.
    assert parse_effect_body("target creature becomes a black zombie in addition to its other types") is None
    assert parse_effect_body("target creature becomes a zombie in addition to its other colors and types") is None


def test_colour_only_addition():
    [spec] = parse_effect_body("target permanent becomes blue in addition to its other colors until end of turn")
    assert spec.params["static"] == {"type": "color", "params": {"colors": ["U"], "set": False}}


def test_copy_exception_adds_the_colour_to_the_copied_ones():
    [spec] = parse_effect_body(
        "create a token that's a copy of that creature, except it's not legendary and it's a 2/2 black zombie "
        "in addition to its other colors and types", group_subject=True)
    assert spec.params["add_colors"] == ["B"] and "set_colors" not in spec.params
    engine, state = _engine()
    white = _bf(state, Card(id="w", name="Lady", type_line="Legendary Creature — Human", is_creature=True,
                            power=3, toughness=3, color_identity={"W"}), "p1")
    [token] = engine.rules.copy_permanent("p1", white, 1, add_colors=["B"], set_power=2, set_toughness=2,
                                          add_subtypes=["Zombie"], not_legendary=True)
    assert set(token.card.color_identity) == {"W", "B"} and (token.card.power, token.card.toughness) == (2, 2)


def test_ratadrabik_is_modeled():
    _modeled("Ratadrabik of Urborg", "Legendary Creature — Zombie Wizard",
             "Whenever another legendary creature you control dies, create a token that's a copy of that "
             "creature, except it's not legendary and it's a 2/2 black Zombie in addition to its other colors "
             "and types.")


# -- attach a chosen Equipment ---------------------------------------------------------


def test_equipment_is_a_target_kind_with_its_scopes():
    from mtg_analyzer.parser.oracle.catalogue.subgrammars import resolve_target_kind

    assert resolve_target_kind("target equipment") == "equipment"
    assert resolve_target_kind("target equipment you control") == "equipment_you_control"
    assert resolve_target_kind("target equipment an opponent controls") == "equipment_you_dont_control"
    assert resolve_target_kind("another target equipment") is None  # the pool doesn't exclude the source


def _equipment(state, name, owner):
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    # The Equip keyword is what makes the object an attachment (`_attachment_kind`).
    obj = _bf(state, Card(id=name, name=name, type_line="Artifact — Equipment", oracle_text="Equip {1}",
                          keywords=["Equip"]), owner)
    bind_from_catalogue(obj)
    return obj


def test_attach_a_chosen_equipment_to_a_chosen_creature():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned

    engine, state = _engine()
    src = _bear(state, "src", "p1")
    sword, host = _equipment(state, "Sword", "p2"), _bear(state, "host", "p2")
    specs = parse_effect_body("attach target equipment to target creature")
    effects = build_effects(specs, src)
    assert len(effects[0].target_specs) == 2
    _apply_effects_partitioned(effects, engine.rules.context, [sword, host], None, source=src)
    assert sword.attached_to == host.instance_id


def test_attach_to_the_source_takes_only_the_equipment_as_a_target():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned

    engine, state = _engine()
    src = _bear(state, "src", "p1")
    sword = _equipment(state, "Sword", "p1")
    effects = build_effects(parse_effect_body("attach target equipment you control to ~"), src)
    assert len(effects[0].target_specs) == 1
    _apply_effects_partitioned(effects, engine.rules.context, [sword], None, source=src)
    assert sword.attached_to == src.instance_id


def test_any_number_of_equipment_all_move():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned

    engine, state = _engine()
    src = _bear(state, "src", "p1")
    a, b = _equipment(state, "A", "p1"), _equipment(state, "B", "p1")
    host = _bear(state, "host", "p1")
    effects = build_effects(parse_effect_body(
        "attach any number of target equipment you control to target creature you control"), src)
    _apply_effects_partitioned(effects, engine.rules.context, [a, b, host], None, source=src)
    assert a.attached_to == host.instance_id and b.attached_to == host.instance_id


def test_declining_the_optional_equipment_attaches_nothing():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned

    engine, state = _engine()
    src = _bear(state, "src", "p1")
    host = _bear(state, "host", "p1")
    effects = build_effects(parse_effect_body(
        "attach up to 1 target equipment you control to target creature you control"), src)
    _apply_effects_partitioned(effects, engine.rules.context, [host], None, source=src)  # equipment declined
    assert host.attached_to is None


def test_the_destination_filter_is_carried():
    [spec] = match_clause("attach up to 1 target equipment you control to target attacking creature")
    assert spec.params["creature_filter"] == {"attacking": True}


def test_real_attach_cards_are_modeled():
    _modeled("Magnetic Theft", "Instant", "Attach target Equipment to target creature.")
    _modeled("Kor Outfitter", "Creature — Kor Soldier", (
        "When Kor Outfitter enters, you may attach target Equipment you control to target creature you control."))
    _modeled("Kazuul's Toll Collector", "Creature — Ogre Warrior", (
        "{0}: Attach target Equipment you control to Kazuul's Toll Collector. Activate only as a sorcery."))


# -- things the real cards exposed once their counter clause parsed ------------------------


def test_kitnaps_stun_counters_go_on_the_enchanted_creature_not_the_aura():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned

    engine, state = _engine()
    host = _bear(state, "host", "p2")
    aura = _bf(state, Card(id="k", name="Kitnap", type_line="Enchantment — Aura"), "p1")
    aura.attached_to = host.instance_id
    specs = parse_effect_body("tap enchanted creature. if the gift wasn't promised, put 3 stun counters on it",
                              self_subject=True)
    assert specs[1].params["previous_subject"] is True
    _apply_effects_partitioned(build_effects(specs, aura), engine.rules.context, None, None, source=aura)
    assert host.tapped and host.counters.get("stun") == 3
    assert not aura.counters.get("stun")


def test_or_fewer_counters_is_an_upper_bound_not_a_counter_called_or_fewer():
    [spec] = parse_effect_body("if ~ has 2 or fewer judgment counters on it, put a judgment counter on ~",
                               self_subject=True)
    assert spec.condition == {"kind": "source_counters", "counter": "judgment", "max": 2}
    # the lower-bound spellings are unchanged
    [spec] = parse_effect_body("if ~ has 3 or more judgment counters on it, put a judgment counter on ~",
                               self_subject=True)
    assert spec.condition["min"] == 3 and spec.condition["counter"] == "judgment"


def test_faithbound_judge_stops_at_three_judgment_counters():
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    from mtg_analyzer.models.game.events import EventType, GameEvent

    engine, state = _engine()
    judge = _bf(state, Card(id="fj", name="Judge", type_line="Creature — Spirit", is_creature=True, power=4,
                            toughness=4, oracle_text="At the beginning of your upkeep, if this creature has two "
                                                     "or fewer judgment counters on it, put a judgment counter on it."),
                "p1")
    bind_from_catalogue(judge)
    engine.begin_turn()
    for _ in range(5):
        state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", player_id="p1"))
        engine.resolve_until_stable()
    assert judge.counters.get("judgment") == 3


def _museum(state, text, name, counters, type_line="Artifact"):
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    obj = _bf(state, Card(id=name, name=name, type_line=type_line, oracle_text=text), "p1")
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    obj.counters.update(counters)
    return obj


def test_plus_an_additional_mana_for_each_named_counter():
    # Famous Museum: the mana ability used to be claimed and then produce a flat {C}.
    engine, state = _engine()
    text = "{T}: Add {C}, plus an additional {C} for each art counter on Famous Museum."
    museum = _museum(state, text, "Famous Museum", {"art": 2})
    engine.begin_turn()
    assert engine.tap_for_mana(state.players[0], museum) == {"C": 3}
    engine2, state2 = _engine()
    empty = _museum(state2, text, "Famous Museum", {})
    engine2.begin_turn()
    assert engine2.tap_for_mana(state2.players[0], empty) == {"C": 1}


def test_x_mana_of_one_colour_where_x_is_the_named_counters():
    # Lotus Blossom: was a flat one mana of any colour, and the counters weren't counted.
    engine, state = _engine()
    text = ("{T}, Sacrifice this artifact: Add X mana of any one color, where X is the number of petal counters "
            "on this artifact.")
    lotus = _museum(state, text, "Lotus Blossom", {"petal": 3})
    engine.begin_turn()
    produced = engine.tap_for_mana(state.players[0], lotus)
    assert sum(produced.values()) == 3 and len(produced) == 1
    assert lotus not in state.battlefield


def test_famous_museum_and_lotus_blossom_are_modeled_with_real_mana():
    _modeled("Famous Museum", "Artifact",
             "Whenever a creature you control dies, put an art counter on Famous Museum.\n"
             "{T}: Add {C}, plus an additional {C} for each art counter on Famous Museum.")

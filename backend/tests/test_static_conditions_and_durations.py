"""RULE 613.6 conditional statics and RULE 611 durations — the two halves of
"as long as", plus MEC-13's attack permission.

Before this, a conditional static meant a new parameter on
`continuous.group_selector_objects` per card family (``active_player_only``,
``min_level``, ``min_count_selector``), each with its own ``if`` and its own
entry in `effects._SELECTOR_KEYS`. "As long as" leads ~250 clauses in the
cache across at least five families, so this is now one whitelisted
vocabulary (`game/static_conditions.py`) evaluated live every recompute,
carried by any static in its ``active_if`` param, with the three older gates
translated into it rather than evaluated separately.

The duration half (`game/durations.py`) is what the per-object ``temp_*``
fields structurally cannot express: those *are* "until end of turn" — cleared
wholesale at cleanup (RULE 514.2) with nowhere to record any other ending.
A RULE 611 continuous effect created by a resolving spell instead lives on
`GameState.floating_statics`, goes through the ordinary layer engine, and is
swept at the window its duration names — including RULE 611.2b's
condition-bounded "for as long as", which *ends* the effect rather than
merely suspending it the way an ``active_if`` gate does.

Reference: mtg_analyzer/game/{static_conditions,durations,continuous,
effects,combat,game_engine}.py, mtg_analyzer/parser/oracle/catalogue/
static_handlers.py.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import combat, continuous, durations, static_conditions
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import EffectRegistry, GrantUntilEffect, StaticAbility
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def _creature(name, oracle_text="", power=2, toughness=2, keywords=None,
              type_line="Creature — Beast"):
    return Card(
        id=name, name=name, type_line=type_line, is_creature=True,
        power=power, toughness=toughness, oracle_text=oracle_text,
        keywords=list(keywords or []), mana_cost_string="{2}{G}",
    )


def _engine(players=(("p1", "Alice", []), ("p2", "Bob", []))):
    return GameEngine.new_game(list(players), starting_life=20, starting_hand=0)


def _put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _modeled(card):
    result = parse_oracle(card)
    assert result.coverage != UNMODELED, result.unclaimed
    assert result.unclaimed == []
    return result


# ---------------------------------------------------------------------------
# The condition vocabulary itself
# ---------------------------------------------------------------------------


def test_no_condition_always_holds():
    eng = _engine()
    assert static_conditions.condition_holds(None, eng.state) is True
    assert static_conditions.condition_holds({}, eng.state) is True


def test_unknown_condition_fails_closed():
    # An unmodeled gate must make the static *not* apply, never apply
    # unconditionally: a static that should be gated but isn't is strictly
    # worse than a card that does nothing.
    eng = _engine()
    obj = _put(eng.state, _creature("Bear"))
    assert static_conditions.condition_holds({"kind": "phase_of_the_moon"}, eng.state, obj) is False


def test_source_tapped_and_untapped_track_live_state():
    eng = _engine()
    obj = _put(eng.state, _creature("Bear"))
    assert static_conditions.condition_holds({"kind": "source_untapped"}, eng.state, obj)
    obj.tapped = True
    assert static_conditions.condition_holds({"kind": "source_tapped"}, eng.state, obj)
    assert not static_conditions.condition_holds({"kind": "source_untapped"}, eng.state, obj)


def test_your_turn_condition_reads_the_active_player():
    eng = _engine()
    obj = _put(eng.state, _creature("Bear"))
    eng.start()
    assert eng.state.active_player.id == "p1"
    assert static_conditions.condition_holds({"kind": "your_turn"}, eng.state, obj, "p1")
    assert not static_conditions.condition_holds({"kind": "your_turn"}, eng.state, obj, "p2")
    assert static_conditions.condition_holds({"kind": "not_your_turn"}, eng.state, obj, "p2")


def test_control_count_condition_uses_the_shared_count_selectors():
    eng = _engine()
    obj = _put(eng.state, _creature("Bear"))
    cond = {"kind": "control_count", "selector": "creatures_you_control", "min": 2}
    assert not static_conditions.condition_holds(cond, eng.state, obj, "p1")
    _put(eng.state, _creature("Second Bear"))
    assert static_conditions.condition_holds(cond, eng.state, obj, "p1")


def test_control_named_condition_is_the_card_on_the_board_case():
    eng = _engine()
    obj = _put(eng.state, _creature("Watcher"))
    cond = {"kind": "control_named", "name": "totem"}
    assert not static_conditions.condition_holds(cond, eng.state, obj, "p1")
    _put(eng.state, _creature("Totem"))
    assert static_conditions.condition_holds(cond, eng.state, obj, "p1")
    # …and it is *your* board, not anyone's.
    eng2 = _engine()
    watcher = _put(eng2.state, _creature("Watcher"))
    _put(eng2.state, _creature("Totem"), controller="p2")
    assert not static_conditions.condition_holds(cond, eng2.state, watcher, "p1")


def test_source_counters_condition_reads_plus_one_counters():
    eng = _engine()
    obj = _put(eng.state, _creature("Bear"))
    cond = {"kind": "source_counters", "counter": "+1/+1", "min": 1}
    assert not static_conditions.condition_holds(cond, eng.state, obj)
    obj.plus_one_counters = 1
    assert static_conditions.condition_holds(cond, eng.state, obj)


def test_life_and_hand_conditions():
    eng = _engine()
    obj = _put(eng.state, _creature("Bear"))
    player = eng.state.player_by_id("p1")
    player.life = 25
    assert static_conditions.condition_holds(
        {"kind": "life_at_least", "amount": 25}, eng.state, obj, "p1")
    assert not static_conditions.condition_holds(
        {"kind": "life_at_least", "amount": 26}, eng.state, obj, "p1")
    assert static_conditions.condition_holds(
        {"kind": "cards_in_hand_at_most", "amount": 0}, eng.state, obj, "p1")


def _put_in_graveyard(state, card, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=Zone.GRAVEYARD)
    state.player_by_id(owner).graveyard.append(obj)
    return obj


def test_subtype_in_graveyard_condition():
    # PAR-30: "as long as there's a `<subtype>` card in your graveyard."
    eng = _engine()
    obj = _put(eng.state, _creature("Bear"))
    cond = {"kind": "subtype_in_graveyard", "subtype": "lesson"}
    assert not static_conditions.condition_holds(cond, eng.state, obj, "p1")

    _put_in_graveyard(eng.state, Card(id="L1", name="Environmental Sciences",
                                      type_line="Sorcery — Lesson", is_sorcery=True))
    assert static_conditions.condition_holds(cond, eng.state, obj, "p1")
    # a Lesson in the *opponent's* graveyard doesn't count ("your")
    eng.state.player_by_id("p1").graveyard.clear()
    _put_in_graveyard(eng.state, Card(id="L2", name="Teachings of the Kirin",
                                      type_line="Enchantment — Lesson"), owner="p2")
    assert not static_conditions.condition_holds(cond, eng.state, obj, "p1")


def test_subtype_in_graveyard_honours_min_and_fails_closed():
    eng = _engine()
    obj = _put(eng.state, _creature("Bear"))
    _put_in_graveyard(eng.state, Card(id="L1", name="A", type_line="Sorcery — Lesson", is_sorcery=True))
    assert static_conditions.condition_holds(
        {"kind": "subtype_in_graveyard", "subtype": "lesson", "min": 1}, eng.state, obj, "p1")
    assert not static_conditions.condition_holds(
        {"kind": "subtype_in_graveyard", "subtype": "lesson", "min": 2}, eng.state, obj, "p1")
    # empty subtype → False, never a crash
    assert not static_conditions.condition_holds(
        {"kind": "subtype_in_graveyard", "subtype": ""}, eng.state, obj, "p1")


def test_subtype_in_graveyard_parser_row():
    from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_condition
    assert static_condition("there's a lesson card in your graveyard") == {
        "kind": "subtype_in_graveyard", "subtype": "lesson"}
    assert static_condition("there is a land card in your graveyard") == {
        "kind": "subtype_in_graveyard", "subtype": "land"}


def test_first_time_flyer_anthem_tracks_the_graveyard_live():
    card = _creature(
        "First-Time Flyer",
        "Flying\nThis creature gets +1/+1 as long as there's a Lesson card in your graveyard.",
        type_line="Creature — Bird", keywords=["Flying"],
    )
    _modeled(card)
    eng = _engine()
    obj = _put(eng.state, card)
    continuous.recompute(eng.state)
    assert (obj.power, obj.toughness) == (2, 2)

    _put_in_graveyard(eng.state, Card(id="L1", name="Lesson One",
                                      type_line="Sorcery — Lesson", is_sorcery=True))
    continuous.recompute(eng.state)
    assert (obj.power, obj.toughness) == (3, 3)

    eng.state.player_by_id("p1").graveyard.clear()
    continuous.recompute(eng.state)
    assert (obj.power, obj.toughness) == (2, 2)


def test_graveyard_has_subtype_intervening_if_on_a_trigger():
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
    specs = parse_effect_body(
        "if there's a lesson card in your graveyard, you gain 2 life"
    )
    assert specs and specs[0].condition == {"graveyard_has_type": "lesson"}

    card = _creature(
        "Walltop Sentries",
        "When this creature dies, if there's a Lesson card in your graveyard, you gain 2 life.",
        type_line="Creature — Wall",
    )
    _modeled(card)


def test_legacy_gate_params_translate_into_the_same_vocabulary():
    # The three pre-existing gates keep their spelling in every shipped spec;
    # they must produce the same conditions rather than a second code path.
    assert static_conditions.condition_from_legacy_params(
        {"active_player_only": True}) == {"kind": "your_turn"}
    assert static_conditions.condition_from_legacy_params(
        {"min_level": 2, "level_counter": "class_level"}
    ) == {"kind": "source_counters", "counter": "class_level", "min": 2}
    assert static_conditions.condition_from_legacy_params(
        {"min_count_selector": "artifacts_you_control", "min_count": 3}
    ) == {"kind": "control_count", "selector": "artifacts_you_control", "min": 3}
    assert static_conditions.condition_from_legacy_params({"subtype": "goblin"}) is None


# ---------------------------------------------------------------------------
# Conditions through the layer engine
# ---------------------------------------------------------------------------


def test_conditional_anthem_turns_itself_on_and_off():
    # The point of evaluating live: no event, no trigger, no bookkeeping —
    # tapping the source removes the anthem on the next recompute.
    card = _creature(
        "Vigil Keeper",
        "As long as Vigil Keeper is untapped, creatures you control get +1/+1.",
    )
    _modeled(card)

    eng = _engine()
    source = _put(eng.state, card)
    bear = _put(eng.state, _creature("Bear"))
    continuous.recompute(eng.state)
    assert bear.power == 3

    source.tapped = True
    continuous.recompute(eng.state)
    assert bear.power == 2

    source.tapped = False
    continuous.recompute(eng.state)
    assert bear.power == 3


def test_conditional_grant_on_a_board_count():
    card = _creature(
        "Metal Watcher",
        "As long as you control 3 or more artifacts, Metal Watcher has flying.",
    )
    _modeled(card)

    eng = _engine()
    source = _put(eng.state, card)
    continuous.recompute(eng.state)
    assert not combat.has(source, "flying")

    for i in range(3):
        _put(eng.state, Card(id=f"a{i}", name=f"Rock {i}", type_line="Artifact"))
    continuous.recompute(eng.state)
    assert combat.has(source, "flying")


def test_trailing_as_long_as_is_the_same_static():
    # Both printed orders must produce identical specs — the wrapper parses
    # the gate and re-enters with the bare static either way.
    lead = static_effect_specs("as long as you control an artifact, creatures you control get +1/+1.")
    trail = static_effect_specs("creatures you control get +1/+1 as long as you control an artifact.")
    assert [(s.type, s.params) for s in lead] == [(s.type, s.params) for s in trail]


def test_unrecognized_condition_leaves_the_whole_clause_unclaimed():
    assert static_effect_specs("as long as ~ is wearing a hat, it has flying.") is None
    # …and specifically does NOT fall through to the ungated static.
    assert static_effect_specs("as long as the moon is full, creatures you control get +1/+1.") is None


def test_legacy_active_player_only_still_works_through_the_new_path():
    # A shipped spec spelling (Nahiri, Storm of Stone) — proof the
    # translation is wired, not just unit-tested.
    ability = EffectRegistry.create(
        "grant_keyword",
        {"keywords": ["first_strike"], "affects": "creatures_you_control",
         "active_player_only": True},
    )
    eng = _engine()
    source = _put(eng.state, _creature("Nahiri"))
    bear = _put(eng.state, _creature("Bear"))
    ability.source = source
    source.static_effects.append(ability)
    eng.start()
    continuous.recompute(eng.state)
    assert combat.has(bear, "first_strike")  # p1's turn

    eng.begin_turn()  # → p2's turn
    continuous.recompute(eng.state)
    assert not combat.has(bear, "first_strike")


# ---------------------------------------------------------------------------
# Durations (RULE 611)
# ---------------------------------------------------------------------------


def _grant_until(eng, targets, duration, condition=None, keywords=("flying",)):
    effect = GrantUntilEffect(
        static={"type": "grant_keyword", "params": {"keywords": list(keywords)}},
        duration=duration,
        condition=condition,
    )
    effect.source = _put(eng.state, _creature("Granter"))
    effect.apply(eng.rules.context, list(targets))
    return effect


def test_grant_until_end_of_turn_applies_then_lapses_at_cleanup():
    eng = _engine()
    bear = _put(eng.state, _creature("Bear"))
    _grant_until(eng, [bear], "end_of_turn")
    assert combat.has(bear, "flying")

    eng.start()
    while eng.state.current_step != "cleanup":
        eng.advance_step()
    eng.advance_step()
    continuous.recompute(eng.state)
    assert not combat.has(bear, "flying")


def test_until_your_next_turn_survives_the_cleanup_that_ends_temp_effects():
    # The duration `temp_*` can't express: it must outlive *this* turn's
    # cleanup and end only when the granting player's next turn begins.
    eng = _engine()
    bear = _put(eng.state, _creature("Bear"))
    eng.start()
    _grant_until(eng, [bear], "your_next_turn")
    assert combat.has(bear, "flying")

    eng.begin_turn()  # → p2's turn: not the granter's, so it holds
    continuous.recompute(eng.state)
    assert eng.state.active_player.id == "p2"
    assert combat.has(bear, "flying")

    eng.begin_turn()  # → p1's turn: the granter's, so it ends
    assert eng.state.active_player.id == "p1"
    assert not combat.has(bear, "flying")


def test_until_end_of_combat_ends_earlier_than_end_of_turn():
    eng = _engine()
    bear = _put(eng.state, _creature("Bear"))
    eng.start()
    while eng.state.current_step != "declare_attackers":
        eng.advance_step()
    _grant_until(eng, [bear], "end_of_combat")
    assert combat.has(bear, "flying")

    while eng.state.current_step != "main2":
        eng.advance_step()
    continuous.recompute(eng.state)
    assert not combat.has(bear, "flying")  # gone well before cleanup


def test_for_as_long_as_ends_permanently_unlike_an_active_if_gate():
    # RULE 611.2b: a condition-bounded *duration* ends the effect for good,
    # where an `active_if` gate would let it come back on.
    eng = _engine()
    bear = _put(eng.state, _creature("Bear"))
    source = _put(eng.state, _creature("Totem"))
    _grant_until(
        eng, [bear], "for_as_long_as",
        condition={"kind": "control_named", "name": "totem"},
    )
    assert combat.has(bear, "flying")

    eng.state.battlefield.remove(source)
    continuous.recompute(eng.state)
    assert not combat.has(bear, "flying")

    # Bringing the named permanent back does NOT revive it — the effect is
    # gone, which is the whole difference from a gate.
    _put(eng.state, _creature("Totem"))
    continuous.recompute(eng.state)
    assert not combat.has(bear, "flying")


def test_floating_static_only_touches_its_chosen_permanents():
    eng = _engine()
    bear = _put(eng.state, _creature("Bear"))
    other = _put(eng.state, _creature("Other Bear"))
    _grant_until(eng, [bear], "end_of_turn")
    assert combat.has(bear, "flying")
    assert not combat.has(other, "flying")


def test_floating_static_outlives_its_source_leaving():
    # RULE 611.2b: the continuous effect is independent of its source.
    eng = _engine()
    bear = _put(eng.state, _creature("Bear"))
    effect = _grant_until(eng, [bear], "end_of_turn")
    eng.state.battlefield.remove(effect.source)
    continuous.recompute(eng.state)
    assert combat.has(bear, "flying")


def test_unknown_duration_is_never_swept_rather_than_swept_immediately():
    # Fail-closed in the visible direction: a mis-parsed duration leaves a
    # lingering effect (obvious on the board) instead of silently deleting a
    # legitimate one.
    assert durations.normalize_duration("until_the_cows_come_home") == "rest_of_game"
    eng = _engine()
    ability = StaticAbility("ability", affects="objects", params={"keywords": ["flying"]})
    ability.duration = "until_the_cows_come_home"
    eng.state.floating_statics.append(ability)
    assert durations.sweep(eng.state, "cleanup") is False
    assert eng.state.floating_statics == [ability]


def test_non_end_of_turn_grants_parse_to_the_duration_primitive():
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause

    specs = match_clause("target creature gains hexproof until your next turn")
    assert [(s.type, s.params["duration"]) for s in specs] == [("grant_until", "your_next_turn")]

    # "Until end of turn" deliberately stays on the existing pump path — one
    # phrasing, one implementation.
    specs = match_clause("target creature gains hexproof until end of turn")
    assert [s.type for s in specs] == ["pump"]

    # An unrecognized duration leaves the clause unclaimed rather than
    # guessing a window.
    assert match_clause("target creature gains hexproof until the cows come home") is None


def test_a_real_card_grants_through_the_duration_primitive_end_to_end():
    card = Card(
        id="ward", name="Ward Spell", type_line="Instant", is_instant=True,
        mana_cost_string="{W}", oracle_text="Target creature gains hexproof until your next turn.",
    )
    _modeled(card)

    eng = _engine()
    bear = _put(eng.state, _creature("Bear"))
    spell = GameObject(card, owner_id="p1", zone=Zone.STACK)
    bind_from_catalogue(spell)
    eng.start()
    for effect in spell.spell_effects:
        effect.source = spell
        effect.apply(eng.rules.context, [bear])

    assert combat.has(bear, "hexproof")
    eng.begin_turn()  # p2's turn — still holds
    continuous.recompute(eng.state)
    assert combat.has(bear, "hexproof")
    eng.begin_turn()  # back to p1 — the granting player's next turn
    assert not combat.has(bear, "hexproof")


def test_lockdown_family_composes_three_previously_separate_pieces():
    # PAR-11, closed by this batch without any new engine primitive: the
    # `previous_subject` pronoun (fight batch), the `no_untap` static (batch
    # 8) and this batch's condition-bounded duration had simply never met.
    card = _creature(
        "Sand Squid",
        "{T}: Tap target land. It doesn't untap during its controller's "
        "untap step for as long as Sand Squid remains tapped.",
        type_line="Creature — Squid",
    )
    _modeled(card)

    eng = _engine()
    squid = _put(eng.state, card)
    land = _put(eng.state, Card(id="l", name="Island", type_line="Land"), controller="p2")
    squid.tapped = True

    # The ability is two clauses: the tap, then the lock referring back to
    # what it tapped. Resolving them in order through the engine's own
    # partitioned path is what maintains `previous_targets`.
    tap, lock = squid.activated_abilities[0].effects
    assert isinstance(lock, GrantUntilEffect)
    for effect in (tap, lock):
        effect.source = squid
    tap.apply(eng.rules.context, [land])
    eng.rules.context.previous_targets = [land]
    lock.apply(eng.rules.context)

    assert continuous.has_no_untap_static(eng.state, land) is True
    # …and it lapses on its own the moment the squid untaps (RULE 611.2b).
    squid.tapped = False
    continuous.recompute(eng.state)
    assert continuous.has_no_untap_static(eng.state, land) is False


# ---------------------------------------------------------------------------
# MEC-13: "can attack as though it didn't have defender"
# ---------------------------------------------------------------------------


def test_attack_permission_lets_a_defender_attack_without_losing_the_keyword():
    card = _creature(
        "Colossus of Akros",
        "Defender\n~ can attack as though it didn't have defender.",
        keywords=["Defender"],
    )
    eng = _engine()
    state = eng.state
    obj = _put(state, card)
    continuous.recompute(state)

    assert combat.has_defender(obj)  # RULE 702.3b: the keyword is still there
    eng.start()
    while state.current_step != "declare_attackers":
        eng.advance_step()
    eng.declare_attackers(state.active_player, [obj])
    assert obj.attacking is True


def test_a_plain_defender_still_cannot_attack():
    # The negative case the permission must not leak into.
    eng = _engine()
    state = eng.state
    obj = _put(state, _creature("Wall", keywords=["Defender"]))
    continuous.recompute(state)
    eng.start()
    while state.current_step != "declare_attackers":
        eng.advance_step()
    with pytest.raises(ValueError):
        eng.declare_attackers(state.active_player, [obj])


def test_colossus_of_akros_full_card_is_modeled_and_behaves():
    # MEC-13's card, end to end: the permission is gated on the RULE 701.37b
    # designation, so it only lifts Defender once the creature is monstrous.
    card = _creature(
        "Colossus of Akros",
        "Defender\n{10}: Monstrosity 10.\n"
        "As long as Colossus of Akros is monstrous, it has trample and can "
        "attack as though it didn't have defender.",
        power=10, toughness=10, keywords=["Defender"],
    )
    _modeled(card)

    eng = _engine()
    state = eng.state
    obj = _put(state, card)
    continuous.recompute(state)
    assert not combat.has(obj, "trample")
    eng.start()
    while state.current_step != "declare_attackers":
        eng.advance_step()
    with pytest.raises(ValueError):
        eng.declare_attackers(state.active_player, [obj])

    eng.rules.monstrosity(obj, 10)
    continuous.recompute(state)
    assert combat.has(obj, "trample")
    eng.declare_attackers(state.active_player, [obj])
    assert obj.attacking is True

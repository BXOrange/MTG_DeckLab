"""MEC-12 (goad's four residues) and MEC-14 (the rest of the "as long as"
vocabulary) — the two tickets that were left open when goad and the general
RULE 613.6 condition machinery shipped.

Neither ticket was really about its headline mechanic. MEC-12's four items are
a targeting-system feature (a target count read off the board), a layer-engine
one (a group filter whose threshold is the source's own derived power), an
effect-composition one (naming the tokens a *previous clause* just created)
and a trigger-subject one (filtering on a designation rather than a
characteristic) — goad is only what made each of them visible first. MEC-14 is
purely widening `game/static_conditions.py`'s whitelist, and the widening that
carried it is the ``of`` **subject selector**: every ``source_*`` kind can now
read the attached permanent instead, which is what ~52 "as long as enchanted
permanent is a creature" cards want.

Reference: mtg_analyzer/game/{static_conditions,durations,continuous,targeting,
effects,effect_binder,rules_engine}.py, mtg_analyzer/parser/oracle/{segmenter,
catalogue/handlers,catalogue/static_handlers}.py.
"""

from __future__ import annotations

from mtg_analyzer.game import combat, continuous, durations, static_conditions
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import (
    TargetSpec,
    collapse_groups,
    expand_counts,
    resolved_count,
)
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.catalogue.static_handlers import (
    static_condition,
    static_effect_specs,
)
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.parser.oracle.spec import ParserProvenance


def _creature(name, oracle_text="", power=2, toughness=2, keywords=None,
              type_line="Creature — Beast"):
    return Card(
        id=name, name=name, type_line=type_line, is_creature=True,
        power=power, toughness=toughness, oracle_text=oracle_text,
        keywords=list(keywords or []), mana_cost_string="{2}{G}",
    )


def _aura(name, oracle_text=""):
    # `Card.is_enchantment` is derived from the type line, not a constructor
    # flag — same as every other secondary type.
    return Card(
        id=name, name=name, type_line="Enchantment — Aura",
        oracle_text=oracle_text, mana_cost_string="{1}{W}",
    )




def _engine(players=(("p1", "Alice", []), ("p2", "Bob", []))):
    return GameEngine.new_game(list(players), starting_life=20, starting_hand=0)


def _put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _fire_etb(eng, obj):
    """Fire `ENTERS_BATTLEFIELD` for an object `_put` placed directly — the
    fixture adds it to the battlefield without the event a real entry path
    would produce."""
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id=obj.controller_id,
        object=obj.name, instance_id=obj.instance_id,
        object_types=sorted(obj.type_words),
    ))


def _segment(line):
    return segment_line(
        line, allow_spell_effect=False, provenance=ParserProvenance("test", "test")
    )


# ---------------------------------------------------------------------------
# MEC-14 — the ``of`` subject selector and the new condition kinds
# ---------------------------------------------------------------------------


def test_attached_subject_reads_the_host_not_the_aura():
    # "As long as enchanted permanent is a creature" — the Aura itself is
    # never a creature, so reading the source would make this permanently
    # false. RULE 303.4a: the condition is about the enchanted permanent.
    eng = _engine()
    host = _put(eng.state, _creature("Bear"))
    aura = _put(eng.state, _aura("Grasp"))
    condition = {"kind": "is_card_type", "card_type": "creature", "of": "attached"}

    assert static_conditions.condition_holds(condition, eng.state, aura, "p1") is False
    aura.attached_to = host.instance_id
    assert static_conditions.condition_holds(condition, eng.state, aura, "p1") is True
    # Source-scoped (the default) is still the Aura, and still false.
    assert static_conditions.condition_holds(
        {"kind": "is_card_type", "card_type": "creature"}, eng.state, aura, "p1"
    ) is False


def test_attached_subject_with_no_host_fails_closed():
    eng = _engine()
    aura = _put(eng.state, _aura("Grasp"))
    for kind in ("source_tapped", "source_untapped", "source_counters"):
        assert static_conditions.condition_holds(
            {"kind": kind, "of": "attached"}, eng.state, aura, "p1"
        ) is False


def test_unknown_subject_fails_closed():
    eng = _engine()
    obj = _put(eng.state, _creature("Bear"))
    assert static_conditions.condition_holds(
        {"kind": "source_untapped", "of": "the_moon"}, eng.state, obj, "p1"
    ) is False


def test_is_color_and_is_subtype_read_derived_characteristics():
    eng = _engine()
    host = _put(eng.state, _creature("Goblin Scout", type_line="Creature — Goblin Scout"))
    host.card.color_identity = ["R"]
    aura = _put(eng.state, _aura("Clout"))
    aura.attached_to = host.instance_id

    assert static_conditions.condition_holds(
        {"kind": "is_color", "color": "R", "of": "attached"}, eng.state, aura, "p1"
    ) is True
    assert static_conditions.condition_holds(
        {"kind": "is_color", "color": "U", "of": "attached"}, eng.state, aura, "p1"
    ) is False
    assert static_conditions.condition_holds(
        {"kind": "is_subtype", "subtype": "goblin", "of": "attached"}, eng.state, aura, "p1"
    ) is True


def test_drawn_cards_this_turn_condition():
    eng = _engine()
    condition = {"kind": "drawn_cards_at_least", "amount": 2}
    assert static_conditions.condition_holds(condition, eng.state, None, "p1") is False
    eng.state.cards_drawn_this_turn["p1"] = 2
    assert static_conditions.condition_holds(condition, eng.state, None, "p1") is True
    # Scoped to the named player, not to whoever drew most.
    assert static_conditions.condition_holds(condition, eng.state, None, "p2") is False


def test_opponent_count_is_satisfied_by_any_one_opponent():
    eng = _engine((("p1", "A", []), ("p2", "B", []), ("p3", "C", [])))
    condition = {"kind": "opponent_count", "selector": "cards_in_your_graveyard", "min": 2}
    assert static_conditions.condition_holds(condition, eng.state, None, "p1") is False
    # Your *own* graveyard must not satisfy an opponent-scoped condition.
    eng.state.player_by_id("p1").graveyard.extend([_creature("A"), _creature("B")])
    assert static_conditions.condition_holds(condition, eng.state, None, "p1") is False
    eng.state.player_by_id("p3").graveyard.extend([_creature("C"), _creature("D")])
    assert static_conditions.condition_holds(condition, eng.state, None, "p1") is True


def test_affected_subject_needs_a_single_referent():
    # PAR-11's residue: "…doesn't untap for as long as **it** has a
    # paralyzation counter on it" — "it" is the locked permanent, which only
    # the floating static holding the object id can resolve.
    eng = _engine()
    locked = _put(eng.state, _creature("Wall"))
    locked.counters["paralyzation"] = 1
    condition = {"kind": "source_counters", "counter": "paralyzation", "min": 1, "of": "affected"}

    # No referent supplied → fails closed.
    assert static_conditions.condition_holds(condition, eng.state, None, "p1") is False
    assert static_conditions.condition_holds(
        condition, eng.state, None, "p1", affected=locked
    ) is True
    locked.counters["paralyzation"] = 0
    assert static_conditions.condition_holds(
        condition, eng.state, None, "p1", affected=locked
    ) is False


def test_for_as_long_as_duration_reads_the_affected_permanent():
    eng = _engine()
    locked = _put(eng.state, _creature("Wall"))
    locked.counters["paralyzation"] = 1
    ability = EffectRegistry.create(
        "no_untap", {"affects": "objects"}
    )
    ability.source = _put(eng.state, _creature("Jailer"))
    ability.object_ids = [locked.instance_id]
    ability.duration = "for_as_long_as"
    ability.duration_data = {
        "condition": {
            "kind": "source_counters", "counter": "paralyzation", "min": 1, "of": "affected",
        }
    }
    eng.state.floating_statics.append(ability)

    assert durations.is_expired(ability, eng.state, "recompute") is False
    locked.counters["paralyzation"] = 0
    assert durations.is_expired(ability, eng.state, "recompute") is True
    # RULE 611.2b: it *ends* — putting the counter back must not revive it.
    durations.sweep(eng.state, "recompute")
    locked.counters["paralyzation"] = 1
    assert eng.state.floating_statics == []


def test_conditional_static_rewrites_it_to_the_attached_subject():
    specs = static_effect_specs(
        "as long as enchanted creature is red, it gets +1/+1 and has haste"
    )
    assert specs is not None
    assert [s.type for s in specs] == ["anthem", "grant_keyword"]
    for spec in specs:
        assert spec.params["affects"] == "attached_permanent"
        assert spec.params["active_if"] == {"kind": "is_color", "color": "R", "of": "attached"}


def test_unknown_attached_characteristic_word_fails_the_whole_clause():
    # Not a card type, colour or whitelisted subtype — the clause must stay
    # unclaimed rather than becoming a subtype filter that never matches.
    assert static_condition("enchanted creature is enraged") is None
    assert static_effect_specs(
        "as long as enchanted creature is enraged, it gets +1/+1"
    ) is None


def test_clout_of_the_dominus_is_modeled_end_to_end():
    card = _aura(
        "Clout of the Dominus",
        "Enchant creature\n"
        "As long as enchanted creature is blue, it gets +1/+1 and has shroud.\n"
        "As long as enchanted creature is red, it gets +1/+1 and has haste.",
    )
    assert parse_oracle(card).coverage != UNMODELED


def test_conditional_anthem_only_applies_while_the_host_matches():
    eng = _engine()
    host = _put(eng.state, _creature("Bear", power=2, toughness=2))
    host.card.color_identity = ["G"]
    aura = _put(eng.state, _aura(
        "Clout", "As long as enchanted creature is red, it gets +1/+1 and has haste."
    ))
    aura.attached_to = host.instance_id
    eng.recompute_continuous_effects()
    assert (host.power, host.toughness) == (2, 2)

    host.card.color_identity = ["R"]
    eng.recompute_continuous_effects()
    assert (host.power, host.toughness) == (3, 3)
    assert combat.has(host, "haste")


# ---------------------------------------------------------------------------
# MEC-14 — RULE 702.94b soulbond finally reaches its selector
# ---------------------------------------------------------------------------


def test_soulbond_quoted_grant_targets_the_pair():
    specs = static_effect_specs(
        'each of those creatures has "whenever ~ deals damage to an opponent, draw a card."'
    )
    assert specs is not None
    assert len(specs) == 1
    assert specs[0].params["affects"] == "soulbond_pair"


def test_soulbond_pair_selector_yields_nothing_while_unpaired():
    eng = _engine()
    a = _put(eng.state, _creature("Stonewright"))
    b = _put(eng.state, _creature("Partner"))
    assert continuous.group_selector_objects(eng.state, "p1", "soulbond_pair", {}, src=a) == []
    a.paired_with = b.instance_id
    b.paired_with = a.instance_id
    picked = continuous.group_selector_objects(eng.state, "p1", "soulbond_pair", {}, src=a)
    assert {o.instance_id for o in picked} == {a.instance_id, b.instance_id}


def test_stonewright_is_modeled_end_to_end():
    card = _creature(
        "Stonewright",
        "Soulbond\n"
        'As long as Stonewright is paired with another creature, each of those '
        'creatures has "{R}: This creature gets +1/+0 until end of turn."',
        type_line="Creature — Human Shaman",
        keywords=["Soulbond"],
    )
    assert parse_oracle(card).coverage != UNMODELED


# ---------------------------------------------------------------------------
# MEC-12(a) — a target count read off the board (RULE 601.2c)
# ---------------------------------------------------------------------------


def test_resolved_count_defaults_to_the_printed_count():
    assert resolved_count(TargetSpec(kind="creature", count=2)) == 2
    # An unknown selector never silently becomes 0.
    assert resolved_count(
        TargetSpec(kind="creature", count=3, count_selector="whatever")
    ) == 3


def test_opponents_count_selector_counts_living_opponents():
    eng = _engine((("p1", "A", []), ("p2", "B", []), ("p3", "C", [])))
    spec = TargetSpec(kind="creature", optional=True, count=1, count_selector="opponents")
    assert resolved_count(spec, eng.state, "p1") == 2


def test_monstrosity_x_count_selector_reads_the_announced_x():
    eng = _engine()
    src = _put(eng.state, _creature("Death Kiss", power=5, toughness=5))
    spec = TargetSpec(kind="creature", optional=True, count=1,
                      count_selector="source_monstrosity_x")
    assert resolved_count(spec, eng.state, "p1", src) == 0
    eng.rules.monstrosity(src, 3)
    assert resolved_count(spec, eng.state, "p1", src) == 3


def test_expand_counts_round_trips_through_collapse_groups():
    single = TargetSpec(kind="creature")
    triple = TargetSpec(kind="creature", optional=True, count=3)
    expanded, spans = expand_counts([single, triple])
    assert spans == [1, 3]
    assert len(expanded) == 4
    assert all(s.count == 1 for s in expanded)
    # The expanded specs' picks collapse back to one group per *original*
    # requirement, which is what `_apply_effects_partitioned` maps onto
    # `GameEffect.target_specs`.
    assert collapse_groups([["a"], ["b"], ["c"], []], spans) == [["a"], ["b", "c"]]


def test_expand_counts_leaves_ordinary_single_target_specs_untouched():
    specs = [TargetSpec(kind="creature"), TargetSpec(kind="player")]
    expanded, spans = expand_counts(specs)
    assert expanded == specs
    assert spans == [1, 1]


def test_goad_per_opponent_clause_parses_to_a_dynamic_count():
    specs = match_clause(
        "for each opponent, goad up to 1 target creature that player controls"
    )
    assert specs is not None
    assert specs[0].type == "goad"
    assert specs[0].params["count_selector"] == "opponents"
    assert specs[0].params["optional"] is True


def test_goad_up_to_x_clause_parses_to_the_monstrosity_x_count():
    specs = match_clause("goad up to x target creatures your opponents control")
    assert specs is not None
    assert specs[0].params["count_selector"] == "source_monstrosity_x"


def test_per_opponent_goad_requires_distinct_controllers():
    # "that player controls" is RULE 115's already-modeled cross-target
    # constraint, not a new one.
    effect = EffectRegistry.create(
        "goad",
        {"target_kind": "creature_you_dont_control", "optional": True,
         "count_selector": "opponents"},
    )
    assert effect.target_spec.distinct_controllers is True


def test_dynamic_count_goad_uses_every_chosen_target():
    eng = _engine((("p1", "A", []), ("p2", "B", []), ("p3", "C", [])))
    src = _put(eng.state, _creature("General"))
    victims = [
        _put(eng.state, _creature("Bear"), controller="p2"),
        _put(eng.state, _creature("Ox"), controller="p3"),
    ]
    effect = EffectRegistry.create(
        "goad",
        {"target_kind": "creature_you_dont_control", "optional": True,
         "count_selector": "opponents"},
    )
    effect.source = src
    effect.apply(eng.rules.context, list(victims))
    assert all(combat.is_goaded(v) for v in victims)


def test_per_opponent_goad_gathers_one_target_per_opponent_end_to_end():
    # The riskiest half of MEC-12(a): the trigger path gathers exactly one
    # pick per spec, so an N-target requirement is offered as N rounds and
    # collapsed back before resolution.
    eng = _engine((("p1", "A", []), ("p2", "B", []), ("p3", "C", [])))
    eng.start()
    victims = [
        _put(eng.state, _creature("Bear"), controller="p2"),
        _put(eng.state, _creature("Ox"), controller="p3"),
    ]
    src = _put(eng.state, _creature(
        "General",
        "When this creature enters, for each opponent, goad up to one target "
        "creature that player controls.",
    ))
    assert src.triggered_abilities, "the trigger must have bound"

    _fire_etb(eng, src)
    eng.resolve_until_stable()

    picked = 0
    while eng.state.pending_choice is not None and picked < 4:
        choice = eng.state.pending_choice
        assert choice["kind"] == "trigger_target_multi"
        # Both a "you may"-style decline and RULE 115.1a's "stop before N"
        # are on offer; take a real target.
        option = next(o for o in choice["options"] if o["id"] not in ("decline", "stop"))
        eng.resolve_pending_choice(option["id"])
        eng.resolve_until_stable()
        picked += 1

    assert picked == 2, "one round per opponent"
    assert all(combat.is_goaded(v) for v in victims)


def test_expanded_requirement_can_stop_before_n():
    eng = _engine((("p1", "A", []), ("p2", "B", []), ("p3", "C", [])))
    eng.start()
    bear = _put(eng.state, _creature("Bear"), controller="p2")
    ox = _put(eng.state, _creature("Ox"), controller="p3")
    src = _put(eng.state, _creature(
        "General",
        "When this creature enters, for each opponent, goad up to one target "
        "creature that player controls.",
    ))
    _fire_etb(eng, src)
    eng.resolve_until_stable()

    choice = eng.state.pending_choice
    assert any(o["id"] == "stop" for o in choice["options"])
    eng.resolve_pending_choice("stop")
    eng.resolve_until_stable()
    # Stopping keeps the ability and resolves it against nothing — unlike a
    # decline, which abandons it. Either way nothing is goaded here, but the
    # ability must not be left dangling.
    assert eng.state.pending_choice is None
    assert not combat.is_goaded(bear)
    assert not combat.is_goaded(ox)


# ---------------------------------------------------------------------------
# MEC-12(b) — a group filter whose threshold is the source's own power
# ---------------------------------------------------------------------------


def test_power_lt_selector_tracks_the_sources_derived_power():
    eng = _engine()
    src = _put(eng.state, _creature("Baeloth", power=4, toughness=4))
    small = _put(eng.state, _creature("Runt", power=1, toughness=1), controller="p2")
    big = _put(eng.state, _creature("Titan", power=7, toughness=7), controller="p2")
    eng.recompute_continuous_effects()

    picked = continuous.group_selector_objects(
        eng.state, "p1", "creatures_opponents_control",
        {"power_lt_selector": "source_power"}, src=src,
    )
    assert {o.instance_id for o in picked} == {small.instance_id}

    # The threshold is *derived* power, so a pump on the source moves it —
    # which is the whole reason it can't be the literal `max_power` the scope
    # already had. 4 → 9 brings the 7-power creature under it.
    src.temp_power = 5
    eng.recompute_continuous_effects()
    picked = continuous.group_selector_objects(
        eng.state, "p1", "creatures_opponents_control",
        {"power_lt_selector": "source_power"}, src=src,
    )
    assert {o.instance_id for o in picked} == {small.instance_id, big.instance_id}
    # …and a pump on the *affected* side is read live too.
    src.temp_power = 0
    small.temp_power = 4  # now 5 power, over the 4-power threshold
    eng.recompute_continuous_effects()
    picked = continuous.group_selector_objects(
        eng.state, "p1", "creatures_opponents_control",
        {"power_lt_selector": "source_power"}, src=src,
    )
    assert picked == []


def test_group_goaded_static_parses_with_the_power_qualifier():
    specs = static_effect_specs(
        "creatures your opponents control with power less than ~'s power are goaded"
    )
    assert specs is not None
    assert specs[0].type == "goaded"
    assert specs[0].params["affects"] == "creatures_opponents_control"
    assert specs[0].params["power_lt_selector"] == "source_power"


def test_group_goaded_static_without_a_qualifier_goads_everyone():
    specs = static_effect_specs("creatures your opponents control are goaded")
    assert specs is not None
    assert "power_lt_selector" not in specs[0].params


def test_baeloths_goaded_static_actually_goads_on_the_board():
    eng = _engine()
    src = _put(eng.state, _creature(
        "Baeloth Barrityl",
        "Creatures your opponents control with power less than Baeloth Barrityl's power are goaded.",
        power=4, toughness=4,
    ))
    small = _put(eng.state, _creature("Runt", power=1, toughness=1), controller="p2")
    big = _put(eng.state, _creature("Titan", power=7, toughness=7), controller="p2")
    eng.recompute_continuous_effects()
    assert combat.is_goaded(small) is True
    assert combat.is_goaded(big) is False


# ---------------------------------------------------------------------------
# MEC-12(c) — naming what a previous clause just created
# ---------------------------------------------------------------------------


def test_create_token_records_what_it_made():
    eng = _engine()
    src = _put(eng.state, _creature("Maker"))
    effect = EffectRegistry.create(
        "create_token",
        {"count": 2, "power": 1, "toughness": 1, "subtypes": ["Warrior"]},
    )
    effect.source = src
    context = eng.rules.context
    context.created_objects = []
    effect.apply(context)
    assert len(context.created_objects) == 2
    assert all(o.is_token for o in context.created_objects)


def test_each_player_creates_gives_everyone_their_own_tokens_tapped():
    eng = _engine((("p1", "A", []), ("p2", "B", []), ("p3", "C", [])))
    src = _put(eng.state, _creature("Saga"))
    effect = EffectRegistry.create(
        "create_token",
        {"count": 1, "power": 1, "toughness": 1, "subtypes": ["Warrior"],
         "creators": "each_player", "tapped": True},
    )
    effect.source = src
    context = eng.rules.context
    context.created_objects = []
    effect.apply(context)
    assert len(context.created_objects) == 3
    assert {o.controller_id for o in context.created_objects} == {"p1", "p2", "p3"}
    assert all(o.tapped for o in context.created_objects)


def test_goad_created_referent_goads_the_new_tokens_permanently():
    eng = _engine((("p1", "A", []), ("p2", "B", [])))
    src = _put(eng.state, _creature("Rendmaw"))
    make = EffectRegistry.create(
        "create_token",
        {"count": 1, "power": 2, "toughness": 2, "subtypes": ["Bird"],
         "creators": "each_player"},
    )
    goad = EffectRegistry.create(
        "goad", {"target_kind": None, "referent": "created", "permanent": True}
    )
    for effect in (make, goad):
        effect.source = src
    context = eng.rules.context
    context.created_objects = []
    make.apply(context)
    goad.apply(context)

    tokens = list(context.created_objects)
    assert len(tokens) == 2
    assert all(combat.is_goaded(t) for t in tokens)
    # "For the rest of the game": the goader's own turn beginning must not
    # end it, unlike RULE 701.15a's printed default.
    assert all(t.goaded_permanently == {"p1"} for t in tokens)
    assert all(t.goaded_by == set() for t in tokens)


def test_ordinary_goad_still_expires_at_the_goaders_next_turn():
    eng = _engine()
    eng.start()
    victim = _put(eng.state, _creature("Bear"), controller="p2")
    eng.rules.goad(victim, "p1")
    assert combat.is_goaded(victim) is True
    # p1 is the starting player, so its *next* turn is two turns away.
    eng.begin_turn()  # → p2's turn: not the goader's, so it holds
    assert eng.state.active_player.id == "p2"
    assert combat.is_goaded(victim) is True
    eng.begin_turn()  # → p1's turn: RULE 701.15a, the goad ends
    assert combat.is_goaded(victim) is False


def test_rest_of_game_goad_survives_the_goaders_turn():
    eng = _engine()
    eng.start()
    victim = _put(eng.state, _creature("Bear"), controller="p2")
    eng.rules.goad(victim, "p1", permanent=True)
    eng.begin_turn()
    eng.begin_turn()
    assert eng.state.active_player.id == "p1"
    assert combat.is_goaded(victim) is True


def test_created_referent_is_scoped_to_one_resolution():
    # `created_objects` must never leak between resolutions — a later,
    # unrelated "the tokens are goaded" would otherwise point at whatever the
    # last spell made.
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned

    eng = _engine()
    src = _put(eng.state, _creature("Maker"))
    make = EffectRegistry.create(
        "create_token", {"count": 1, "power": 1, "toughness": 1, "subtypes": ["Bird"]}
    )
    context = eng.rules.context
    _apply_effects_partitioned([make], context, None, None, source=src)
    assert context.created_objects == []


def test_each_player_creates_tapped_token_clause_parses():
    specs = match_clause(
        "each player creates a tapped 2/2 black bird creature token with flying"
    )
    assert specs is not None
    assert specs[0].params["creators"] == "each_player"
    assert specs[0].params["tapped"] is True
    assert specs[0].params["keywords"] == ["flying"]


def test_plain_create_token_clause_is_unchanged():
    specs = match_clause("create a 1/1 white soldier creature token")
    assert specs is not None
    assert "creators" not in specs[0].params
    assert "tapped" not in specs[0].params


def test_the_tokens_are_goaded_clause_parses():
    specs = match_clause("the tokens are goaded for the rest of the game")
    assert specs is not None
    assert specs[0].params == {"target_kind": None, "referent": "created", "permanent": True}


# ---------------------------------------------------------------------------
# MEC-12(d) — a trigger subject filtered on a designation
# ---------------------------------------------------------------------------


def test_goaded_trigger_subject_is_recognised():
    segment = _segment("whenever a goaded creature attacks, you draw a card.")
    assert segment.claimed
    condition = segment.spec.trigger["condition"]
    assert condition["goaded"] is True
    assert condition["in_combat"] is False


def test_goaded_attacking_or_blocking_trigger_subject_is_recognised():
    segment = _segment(
        "whenever a goaded attacking or blocking creature dies, you draw a card."
    )
    assert segment.claimed
    condition = segment.spec.trigger["condition"]
    assert condition["goaded"] is True
    assert condition["in_combat"] is True


def test_ungoaded_group_trigger_carries_no_designation_filter():
    segment = _segment("whenever a creature dies, you draw a card.")
    assert segment.claimed
    assert "goaded" not in segment.spec.trigger["condition"]


def test_goaded_dies_trigger_only_fires_for_a_goaded_creature():
    eng = _engine()
    watcher = _put(eng.state, _creature(
        "Baeloth", "Whenever a goaded creature dies, you draw a card."
    ))
    assert watcher.triggered_abilities, "the watcher's trigger must have bound"

    plain = _put(eng.state, _creature("Bear"), controller="p2")
    goaded = _put(eng.state, _creature("Ox"), controller="p2")
    eng.rules.goad(goaded, "p1")

    library = eng.state.player_by_id("p1").library
    library.extend([_creature(f"Card{i}") for i in range(4)])

    before = len(eng.state.player_by_id("p1").hand)
    eng.rules.destroy(plain)
    eng.resolve_until_stable()
    assert len(eng.state.player_by_id("p1").hand) == before

    eng.rules.destroy(goaded)
    eng.resolve_until_stable()
    assert len(eng.state.player_by_id("p1").hand) == before + 1


def test_goaded_damage_trigger_subject_is_recognised():
    segment = _segment(
        "whenever a goaded creature deals combat damage to 1 of your opponents, "
        "you draw a card."
    )
    assert segment.claimed
    assert segment.spec.trigger["condition"]["goaded"] is True
    assert segment.spec.trigger["filter"]["is_player"] is True


# ---------------------------------------------------------------------------
# The board's view of a continuous effect's bounds
# ---------------------------------------------------------------------------


def test_active_static_abilities_report_duration_and_condition():
    eng = _engine()
    src = _put(eng.state, _creature(
        "Colossus", "As long as Colossus is monstrous, it has trample."
    ))
    rows = [r for r in continuous.active_static_abilities(eng.state) if r["source"] == "Colossus"]
    assert rows, "the conditional static must appear in the panel"
    row = rows[0]
    assert row["condition"] == "solange monströs"
    assert row["duration"] == ""  # a standing static has no duration
    assert row["active"] is False  # not monstrous yet

    eng.rules.monstrosity(src, 1)
    eng.recompute_continuous_effects()
    row = [r for r in continuous.active_static_abilities(eng.state) if r["source"] == "Colossus"][0]
    assert row["active"] is True


def test_duration_describe_covers_every_whitelisted_duration():
    class _Ability:
        def __init__(self, duration, data=None):
            self.duration = duration
            self.duration_data = data or {}
            self.source = None

    assert durations.describe(_Ability(None)) == ""
    assert durations.describe(_Ability("rest_of_game")) == ""
    assert durations.describe(_Ability("end_of_combat")) == "bis Kampfende"
    assert durations.describe(_Ability("your_next_turn")) == "bis zu deinem nächsten Zug"
    assert durations.describe(
        _Ability("for_as_long_as", {"condition": {"kind": "source_tapped"}})
    ) == "bis solange getappt"
    # An unrecognised duration is never swept, and must not claim to end.
    assert durations.describe(_Ability("until_the_heat_death")) == ""

"""ENG-36 — the structured resolution-time condition vocabulary.

`EffectSpec.condition` was 44 flat boolean keys and `ConditionalEffect.
_condition_holds` was 554 lines of one ``if`` per key. They were never 44
questions: a handful of predicates were written out once per *referent*
(``source_has_subtype`` / ``previous_target_has_subtype``), once per
*threshold* (``ring_tempted_at_least`` / ``ring_tempted_at_most``), and once
per *attribute* (eight keys that each read one boolean the engine had
already stamped). `game/effect_conditions.py` factors that apart into
``{kind, of, min/max}`` over `game/static_conditions.py`'s state predicates,
and the flat spellings keep working through a translation table.

What this file pins:

* the two sides of that translation can't drift apart (every flat key
  translates; every structured result is a real kind, subject and field);
* the collapse is real — the pairs above land on *one* kind;
* the three-valued evaluation that makes ``not`` correct, which the flat
  vocabulary could only approximate by hand;
* the parser's fifteen prefix/suffix gates still peel, now through one rule.

Behaviour per condition is covered where it always was — by the card tests
that own each gate (`test_par17_kicked_trigger_gate.py`,
`test_par29_clash.py`, `test_controls_none_of_type_condition.py`, …), which
this change left green.

Reference: mtg_analyzer/game/{effect_conditions,static_conditions}.py,
mtg_analyzer/parser/oracle/{segmenter,spec}.py.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import effect_conditions as ec
from mtg_analyzer.game import static_conditions as sc
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.segmenter import (
    _CONDITION_PREFIXES,
    _CONDITION_SUFFIXES,
    parse_effect_body,
)
from mtg_analyzer.parser.oracle.spec import (
    _ALLOWED_CONDITION_KEYS,
    _STRUCTURED_CONDITION_FIELDS,
    AbilitySpec,
    EffectSpec,
    SpecValidationError,
)


#: One plausible value per flat key, so the translation table can be walked
#: exhaustively rather than sampled. Both polarities where the key has them.
_LEGACY_SAMPLES: dict[str, list[object]] = {
    "kicked": [True, False],
    "kicked_at_least": [2],
    "bargained": [True],
    "additional_cost_paid": [True, False],
    "source_was_cast": [True, False],
    "source_was_foretold": [True],
    "cast_via_escape": [True],
    "cast_outside_sorcery_speed": [True],
    "source_is_renowned": [True, False],
    "previous_target_is_suspected": [True, False],
    "source_entered_untapped": [True, False],
    "source_x_paid_at_least": [5],
    "source_has_subtype": ["Detective"],
    "previous_target_has_subtype": ["goat"],
    "previous_target_is_creature": [True, False],
    "previous_target_is_equipped": [True, False],
    "target_is_controller": [True, False],
    "counter_recipient_is_you": [True, False],
    "target_is_player": [True, False],
    "is_ring_bearer": [True, False],
    "previous_target_power_at_least": [7],
    "previous_target_power_at_most": [2],
    "ring_tempted_at_least": [3],
    "ring_tempted_at_most": [3],
    "no_spells_cast_last_turn": [True],
    "two_or_more_spells_cast_last_turn": [True],
    "is_first_combat_phase": [True, False],
    "life_gained_this_turn_at_least": [3],
    "opponent_lost_life_this_turn_at_least": [3],
    "creatures_died_this_turn_at_least": [1],
    "cards_in_graveyard_at_least": [7],
    "instant_sorcery_cards_in_graveyard_at_least": [2],
    "graveyard_has_type": ["elf"],
    "controls_none_of_type": ["food"],
    "count_selector_at_least": [{"selector": "lands_you_control", "count": 8}],
    "controls_creature_power_at_least": [4],
    "no_creatures_on_battlefield": [True],
    "is_your_turn": [True, False],
    "opponent_cast_color_this_turn": [["U", "B"]],
    "did_all_bends_this_turn": [True],
    "clash_won": [True, False],
    "not_already_exerted": [True],
    "shares_type_with_linked_exile": [True],
    "entering_object_unique_name": [True],
}


def _translated() -> list[tuple[str, object, dict]]:
    """Every (key, value, structured condition) the translator can produce."""
    rows = []
    for key, samples in _LEGACY_SAMPLES.items():
        for value in samples:
            translated = ec.condition_from_legacy({key: value})
            if translated is not None:
                rows.append((key, value, translated))
    return rows


def _walk(condition: dict):
    """A structured condition and every sub-condition inside it."""
    yield condition
    for sub in condition.get("conditions") or []:
        yield from _walk(sub)
    inner = condition.get("condition")
    if isinstance(inner, dict):
        yield from _walk(inner)


class TestVocabularyIsClosed:
    """Nothing may name a predicate, referent or field that doesn't exist.

    The `kind` vocabulary lives in `game/`, which `parser/oracle/` must not
    import (docs/09), so `spec.py` can only check a structured condition's
    *shape*. These tests are the other half of that split: they are what
    stops a kind this repo emits from silently drifting out of the
    vocabulary that evaluates it — the same drift that let
    ``ring_tempted_at_most`` ship unwhitelisted until ENG-37.
    """

    def test_every_flat_key_has_a_translation(self) -> None:
        assert ec.LEGACY_CONDITION_KEYS == _ALLOWED_CONDITION_KEYS

    def test_every_flat_key_has_a_sample(self) -> None:
        # Otherwise the exhaustive walks below would quietly skip a key.
        assert set(_LEGACY_SAMPLES) == ec.LEGACY_CONDITION_KEYS

    @pytest.mark.parametrize("key,value,condition", _translated(), ids=lambda a: str(a)[:40])
    def test_translation_names_only_real_kinds_subjects_and_fields(
        self, key: str, value: object, condition: dict
    ) -> None:
        for node in _walk(condition):
            assert node["kind"] in ec.EFFECT_CONDITION_KINDS, (key, node)
            if "of" in node:
                assert node["of"] in ec.CONDITION_SUBJECTS, (key, node)
            if "flag" in node:
                assert node["flag"] in sc.SUBJECT_FLAGS, (key, node)
            for field in node:
                if field in ("kind", "conditions", "condition"):
                    continue
                assert field in _STRUCTURED_CONDITION_FIELDS, (key, node)

    @pytest.mark.parametrize("key,value,condition", _translated(), ids=lambda a: str(a)[:40])
    def test_translation_passes_spec_validation(
        self, key: str, value: object, condition: dict
    ) -> None:
        # A producer must be able to emit the structured form directly, not
        # only reach it through the translator.
        AbilitySpec._validate_condition(condition)

    def test_the_two_vocabularies_do_not_overlap(self) -> None:
        # A `kind` defined in both modules would make delegation ambiguous:
        # `effect_conditions` answers its own rows first, so a shared name
        # would silently shadow the state one.
        assert not (ec.CONTEXT_CONDITION_KINDS & sc.STATIC_CONDITION_KINDS)

    def test_no_flag_is_dead(self) -> None:
        used = {
            node["flag"]
            for _, _, condition in _translated()
            for node in _walk(condition)
            if "flag" in node
        }
        assert used == sc.SUBJECT_FLAGS, (
            "a `SUBJECT_FLAGS` entry nothing produces is an attribute read "
            "whitelisted for no card — the whitelist is only meaningful "
            "while every row has a reason to be there."
        )


class TestTheCollapseIsReal:
    """The point of the refactor, asserted rather than described.

    Each pair below was two unrelated flat keys with no recorded
    relationship. If a future change re-splits one of them, this fails.
    """

    def test_one_quantity_at_two_thresholds_is_one_kind(self) -> None:
        low = ec.condition_from_legacy({"ring_tempted_at_least": 3})
        high = ec.condition_from_legacy({"ring_tempted_at_most": 3})
        assert low["kind"] == high["kind"] == "ring_tempted"
        assert low == {"kind": "ring_tempted", "min": 3}
        assert high == {"kind": "ring_tempted", "max": 3}

        none = ec.condition_from_legacy({"no_spells_cast_last_turn": True})
        two = ec.condition_from_legacy({"two_or_more_spells_cast_last_turn": True})
        assert none["kind"] == two["kind"] == "spells_cast_last_turn"

        at_least = ec.condition_from_legacy({"previous_target_power_at_least": 7})
        at_most = ec.condition_from_legacy({"previous_target_power_at_most": 2})
        assert at_least["kind"] == at_most["kind"] == "power"

    def test_one_predicate_at_two_referents_is_one_kind(self) -> None:
        mine = ec.condition_from_legacy({"source_has_subtype": "Detective"})
        theirs = ec.condition_from_legacy({"previous_target_has_subtype": "goat"})
        assert mine["kind"] == theirs["kind"] == "is_subtype"
        assert mine.get("of") is None  # the source is the default referent
        assert theirs["of"] == "previous_target"

        target = ec.condition_from_legacy({"target_is_controller": True})
        recipient = ec.condition_from_legacy({"counter_recipient_is_you": True})
        assert target["kind"] == recipient["kind"] == "is_you"
        assert {target["of"], recipient["of"]} == {"target", "counter_recipient"}

    def test_eight_flat_keys_were_one_attribute_read(self) -> None:
        flags = {
            key for key, _, condition in _translated()
            if condition.get("kind") == "flag"
            or condition.get("condition", {}).get("kind") == "flag"
        }
        assert flags == {
            "bargained", "additional_cost_paid", "source_was_cast",
            "source_was_foretold", "cast_via_escape",
            "cast_outside_sorcery_speed", "source_is_renowned",
            "previous_target_is_suspected",
        }

    def test_a_negative_boolean_is_the_not_combinator(self) -> None:
        assert ec.condition_from_legacy({"source_is_renowned": False}) == {
            "kind": "not", "condition": {"kind": "flag", "flag": "renowned"},
        }

    def test_several_flat_keys_fold_into_all(self) -> None:
        # Frodo, Adventurous Hobbit's own compound gate.
        folded = ec.condition_from_legacy(
            {"is_ring_bearer": True, "ring_tempted_at_least": 3}
        )
        assert folded == {
            "kind": "all",
            "conditions": [
                {"kind": "is_ring_bearer"},
                {"kind": "ring_tempted", "min": 3},
            ],
        }

    def test_a_structured_condition_passes_through_untouched(self) -> None:
        structured = {"kind": "kicked", "min": 1}
        assert ec.condition_from_legacy(structured) is structured


def _context() -> tuple[GameContext, GameObject]:
    engine = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    source = GameObject(
        Card(id="src", name="Source", type_line="Creature — Human", is_creature=True,
             power=1, toughness=1),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    engine.state.add_to_battlefield(source)
    return GameContext(engine.state, engine.rules), source


class TestThreeValuedEvaluation:
    """"No referent" is not "the answer is no" — see the module docstring.

    The flat vocabulary hard-coded this where it mattered (the
    ``previous_target_*`` family shared a "no previous target → false" guard;
    ``clash_won`` checked ``outcome is None`` before comparing either
    branch) and had no way to say it anywhere else. Making it a property of
    the evaluator is what lets every negative gate be spelled ``not``.
    """

    def test_a_missing_referent_fails_both_polarities(self) -> None:
        context, source = _context()
        positive = {"kind": "is_subtype", "of": "previous_target", "subtype": "goat"}
        negative = {"kind": "not", "condition": positive}
        # Nothing was chosen by an earlier clause, so "that creature is a
        # Goat" and "that creature isn't a Goat" are both unanswerable.
        assert ec.condition_holds(positive, context, source) is False
        assert ec.condition_holds(negative, context, source) is False

    def test_a_present_referent_answers_both_polarities(self) -> None:
        context, source = _context()
        goat = GameObject(
            Card(id="g", name="Goat", type_line="Creature — Goat", is_creature=True,
                 power=0, toughness=1),
            owner_id="p1", zone=Zone.BATTLEFIELD,
        )
        context.state.add_to_battlefield(goat)
        context.previous_targets = [goat]
        positive = {"kind": "is_subtype", "of": "previous_target", "subtype": "goat"}
        assert ec.condition_holds(positive, context, source) is True
        assert ec.condition_holds({"kind": "not", "condition": positive}, context, source) is False

        positive = {"kind": "is_subtype", "of": "previous_target", "subtype": "elf"}
        assert ec.condition_holds(positive, context, source) is False
        assert ec.condition_holds({"kind": "not", "condition": positive}, context, source) is True

    def test_no_clash_in_scope_fires_neither_branch(self) -> None:
        # RULE 701.30d — a stray "otherwise, …" must not resolve just
        # because no clash happened.
        context, source = _context()
        assert ec.condition_holds({"kind": "clash_won"}, context, source) is False
        assert ec.condition_holds(
            {"kind": "not", "condition": {"kind": "clash_won"}}, context, source
        ) is False
        context.clash_won = False
        assert ec.condition_holds(
            {"kind": "not", "condition": {"kind": "clash_won"}}, context, source
        ) is True

    def test_all_is_unanswerable_if_any_member_is(self) -> None:
        context, source = _context()
        combined = {
            "kind": "all",
            "conditions": [
                {"kind": "your_turn"},
                {"kind": "is_subtype", "of": "previous_target", "subtype": "goat"},
            ],
        }
        assert ec.condition_holds({"kind": "not", "condition": combined}, context, source) is False

    def test_no_condition_at_all_always_holds(self) -> None:
        context, source = _context()
        assert ec.condition_holds(None, context, source) is True
        assert ec.condition_holds({}, context, source) is True

    def test_an_unknown_kind_fails_closed(self) -> None:
        context, source = _context()
        assert ec.condition_holds({"kind": "no_such_predicate"}, context, source) is False
        # …and so does a negation of one: fail-closed must not be invertible
        # into a gate that always fires.
        assert ec.condition_holds(
            {"kind": "not", "condition": {"kind": "no_such_predicate"}}, context, source
        ) is False

    def test_an_empty_negation_fails_closed(self) -> None:
        context, source = _context()
        assert ec.condition_holds({"kind": "not"}, context, source) is False


class TestStateVocabularyIsReachable:
    """An effect condition may name any state predicate, not a parallel set.

    This is the reason the split is worth having: a predicate written for a
    RULE 613.6 static is immediately usable as a RULE 603.4 intervening-if
    with no work in `effect_conditions` at all.
    """

    def test_a_static_only_kind_evaluates_as_an_effect_gate(self) -> None:
        context, source = _context()
        # "as long as you control an artifact" — never a flat condition key,
        # and now usable as one without a new branch anywhere.
        gate = {"kind": "control_count", "selector": "artifacts_you_control", "min": 1}
        assert ec.condition_holds(gate, context, source) is False
        artifact = GameObject(
            Card(id="a", name="Rock", type_line="Artifact"),
            owner_id="p1", zone=Zone.BATTLEFIELD,
        )
        context.state.add_to_battlefield(artifact)
        assert ec.condition_holds(gate, context, source) is True

    def test_a_subject_scoped_kind_is_pointed_at_an_effect_referent(self) -> None:
        context, source = _context()
        source.tapped = True
        # `source_tapped` is a state predicate about "the source"; ``of``
        # re-points it at a referent only a resolving ability has.
        assert ec.condition_holds({"kind": "source_tapped"}, context, source) is True
        other = GameObject(
            Card(id="o", name="Other", type_line="Creature — Elf", is_creature=True,
                 power=1, toughness=1),
            owner_id="p1", zone=Zone.BATTLEFIELD,
        )
        context.state.add_to_battlefield(other)
        assert ec.condition_holds(
            {"kind": "source_tapped", "of": "target"}, context, source, [other]
        ) is False


class TestOnePeelerRule:
    """The parser's fifteen gates, through one rule (`_peel_condition`).

    Each row below is a body that used to have its own ten-line block in
    `parse_effect_body`. The assertion is deliberately just "it still peels,
    and what it emits is a legal structured condition" — which gate means
    what is each card test's own subject.
    """

    BODIES = [
        "draw a card if an opponent lost 3 or more life this turn",
        "if this spell was kicked, draw a card",
        "if it was kicked twice, draw a card",
        "if this spell was bargained, draw a card",
        "if this spell's additional cost was paid, draw a card",
        "if that player is you, draw a card",
        "if that player isn't you, draw a card",
        "if you win, draw a card",
        "otherwise, draw a card",
        "if you gained 3 or more life this turn, draw a card",
        "if you don't control a food, create a food token",
        "if there's a lesson card in your graveyard, draw a card",
        "if no spells were cast last turn, transform ~",
        "if a player cast 2 or more spells last turn, transform ~",
        "if it's the first combat phase of the turn, draw a card",
        "if you chose a creature other than ~ as your ring-bearer, draw a card",
        "if ~ is your ring-bearer and the ring has tempted you 3 or more times "
        "this game, draw a card",
        "draw a card unless her additional cost was paid",
    ]

    @pytest.mark.parametrize("body", BODIES)
    def test_each_gate_still_peels_and_emits_a_valid_condition(self, body: str) -> None:
        specs = parse_effect_body(body)
        assert specs, body
        assert all(spec.condition for spec in specs), body
        for spec in specs:
            AbilitySpec._validate_condition(spec.condition)
            for node in _walk(spec.condition):
                assert node["kind"] in ec.EFFECT_CONDITION_KINDS, (body, node)

    def test_every_table_row_is_exercised(self) -> None:
        # A row nobody probes is a gate nobody knows still works.
        matched = set()
        for body in self.BODIES:
            for index, row in enumerate(_CONDITION_PREFIXES + _CONDITION_SUFFIXES):
                if row.pattern.match(body):
                    matched.add(index)
                    break
        assert len(matched) == len(_CONDITION_PREFIXES) + len(_CONDITION_SUFFIXES)

    def test_an_unclaimed_rest_fails_the_whole_body(self) -> None:
        # Emitting the effect without its gate would be a *wrong* card, which
        # is worse than an unmodeled one — the reason these run before
        # `match_clause`.
        assert parse_effect_body("if this spell was kicked, do something unmodeled") is None

    def test_a_trailing_sentence_keeps_its_own_gate(self) -> None:
        # Frodo, Adventurous Hobbit: "if A, effect1. Then if B, effect2." is
        # two independently gated sentences, not one condition over both.
        specs = parse_effect_body(
            "if you gained 3 or more life this turn, draw a card. "
            "then if ~ is your ring-bearer and the ring has tempted you 3 or more "
            "times this game, you gain 3 life"
        )
        assert specs is not None and len(specs) == 2
        assert specs[0].condition == {"kind": "gained_life_this_turn", "amount": 3}
        assert specs[1].condition["kind"] == "all"


class TestStructuredConditionValidation:
    """`spec.py` checks the shape; the evaluator checks the name."""

    def test_a_structured_condition_needs_a_kind(self) -> None:
        with pytest.raises(SpecValidationError, match="needs a 'kind'"):
            AbilitySpec._validate_condition({"kind": ""})

    def test_an_unknown_field_is_rejected(self) -> None:
        with pytest.raises(SpecValidationError, match="unknown effect condition field"):
            AbilitySpec._validate_condition({"kind": "kicked", "oops": 1})

    def test_a_bool_where_a_count_belongs_is_rejected(self) -> None:
        with pytest.raises(SpecValidationError, match="must be an int"):
            AbilitySpec._validate_condition({"kind": "kicked", "min": True})

    def test_absurd_combinator_nesting_fails_closed(self) -> None:
        node: dict = {"kind": "kicked", "min": 1}
        for _ in range(AbilitySpec.MAX_SPEC_DEPTH + 4):
            node = {"kind": "not", "condition": node}
        with pytest.raises(SpecValidationError, match="nested too deeply"):
            AbilitySpec._validate_condition(node)

    def test_a_structured_condition_survives_a_full_spec_validation(self) -> None:
        spec = AbilitySpec(
            ability_kind="spell_effect",
            effects=[EffectSpec("draw", {"count": 1},
                                condition={"kind": "kicked", "min": 1})],
        )
        spec.validate()


class TestAnyCombinatorAndAmountCompare:
    """ENG-37 B5 — `any` (OR to `all`'s AND) and `amount_compare` (a
    number-vs-number gate over two `effect_amounts` measurements)."""

    def test_any_is_three_valued_or(self) -> None:
        context, source = _context()
        true = {"kind": "your_turn"}   # p1 is active in a fresh game
        false = {"kind": "not_your_turn"}
        unknown = {"kind": "is_subtype", "of": "previous_target", "subtype": "goat"}

        assert ec.condition_holds({"kind": "any", "conditions": [false, true]}, context, source) is True
        assert ec.condition_holds({"kind": "any", "conditions": [false, false]}, context, source) is False
        # none true, one unanswerable -> unanswerable (not False)
        assert ec._evaluate(
            {"kind": "any", "conditions": [false, unknown]}, context, source, None
        ) is None

    def test_amount_compare_reads_two_referents(self) -> None:
        context, source = _context()
        source.counters["loyalty"] = 3
        creature = GameObject(
            Card(id="c3", name="Three", type_line="Creature — Elf", is_creature=True,
                 converted_mana_cost=3, power=1, toughness=1),
            owner_id="p1", zone=Zone.LIBRARY,
        )
        context.state.player_by_id("p1").library.append(creature)
        context.revealed_card = creature

        le = {"kind": "amount_compare", "op": "le",
              "left": {"kind": "characteristic", "characteristic": "mana_value", "of": "revealed"},
              "right": {"kind": "counters", "counter": "loyalty", "of": "source"}}
        assert ec.condition_holds(le, context, source) is True   # 3 <= 3

        source.counters["loyalty"] = 2
        assert ec.condition_holds(le, context, source) is False  # 3 <= 2

        gt = {**le, "op": "gt"}
        assert ec.condition_holds(gt, context, source) is True   # 3 > 2

    def test_amount_compare_unknown_op_is_unanswerable(self) -> None:
        context, source = _context()
        assert ec._evaluate(
            {"kind": "amount_compare", "op": "spaceship",
             "left": {"kind": "fixed", "amount": 1},
             "right": {"kind": "fixed", "amount": 2}},
            context, source, None,
        ) is None

    def test_amount_compare_reads_a_trigger_event_field(self) -> None:
        # Counterbalance: "if it has the same mana value as the revealed
        # card" — right-hand side is the firing SPELL_CAST event's own
        # `mana_value`.
        from mtg_analyzer.models.game.events import EventType, GameEvent

        context, source = _context()
        creature = GameObject(
            Card(id="c2", name="Two", type_line="Creature — Elf", is_creature=True,
                 converted_mana_cost=2, power=1, toughness=1),
            owner_id="p1", zone=Zone.LIBRARY,
        )
        context.state.player_by_id("p1").library.append(creature)
        context.revealed_card = creature
        context.trigger_event = GameEvent(EventType.SPELL_CAST, mana_value=2)

        match = {"kind": "amount_compare", "op": "eq",
                 "left": {"kind": "characteristic", "characteristic": "mana_value",
                          "of": "revealed"},
                 "right": {"kind": "trigger_event", "field": "mana_value"}}
        assert ec.condition_holds(match, context, source) is True

        context.trigger_event = GameEvent(EventType.SPELL_CAST, mana_value=5)
        assert ec.condition_holds(match, context, source) is False

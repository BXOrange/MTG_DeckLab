"""ENG-37 — the five composite IR nodes (`14_` S3's composition axis).

`14_` §1.1 describes the registered effect types as a cross-product of
operation × operands × **composition** × linkage, of which the composition
axis did not exist: an `AbilitySpec` could hold a *list*, and that was the
only way to combine effects. Everything else — branching, "you may",
iteration, "…equal to" — had to be welded into a new registered type, which
is what `game/isa.py` counts 84 of.

`game/effects/composition.py` is that axis: ``seq``, ``if_else``,
``optional``, ``for_each``, ``bind``. What this file pins:

* each node's own behaviour, through a real `GameEngine`;
* that they nest, and that a body inherits the referents of the clause chain
  it sits in;
* the three-valued ``if_else`` — an unanswerable condition runs **neither**
  branch, which is the whole reason `effect_conditions` distinguishes "no"
  from "unanswerable";
* that a body which pauses on a choice suspends correctly, including
  `for_each` asking once per item;
* RULE 601.2c: only ``seq`` may announce its body's targets.

Reference: mtg_analyzer/game/effects/composition.py,
mtg_analyzer/game/effect_amounts.py, mtg_analyzer/game/isa.py.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import isa
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects import composition
from mtg_analyzer.game.effects.core import (
    EffectRegistry, GameContext, _apply_effects_partitioned,
)
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec, SpecValidationError


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _creature(state, owner="p1", name="Bear", power=2, toughness=2):
    obj = GameObject(
        Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
             power=power, toughness=toughness),
        owner_id=owner, zone=Zone.BATTLEFIELD,
    )
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj


def _run(eng, specs, source=None, targets=None):
    context = GameContext(eng.state, eng.rules)
    return _apply_effects_partitioned(
        build_effects(specs, source), context, targets, None, source=source
    )


def _life(eng, player_id="p1"):
    return eng.state.player_by_id(player_id).life


class TestSeq:
    def test_a_body_runs_in_order(self) -> None:
        eng = _engine()
        _run(eng, [EffectSpec("seq", {"effects": [
            {"type": "gain_life", "params": {"amount": 2}},
            {"type": "gain_life", "params": {"amount": 3}},
        ]})])
        assert _life(eng) == 25

    def test_an_empty_body_is_a_no_op(self) -> None:
        eng = _engine()
        _run(eng, [EffectSpec("seq", {"effects": []})])
        assert _life(eng) == 20

    def test_it_announces_its_bodys_targets(self) -> None:
        # RULE 601.2c — a `seq` runs every part, so every part's requirement
        # is announced when the ability goes on the stack.
        effect = build_effects([EffectSpec("seq", {"effects": [
            {"type": "destroy", "params": {"target_kind": "creature"}},
            {"type": "gain_life", "params": {"amount": 2}},
        ]})], None)[0]
        assert [spec.kind for spec in effect.target_specs] == ["creature"]

    @pytest.mark.parametrize("node", ["if_else", "optional", "for_each", "bind"])
    def test_the_other_nodes_announce_nothing(self, node: str) -> None:
        # None of them knows at announce time whether — or how often — its
        # body runs, so none may claim a RULE 115 requirement of its own.
        effect = build_effects([EffectSpec(node, {"effects": [
            {"type": "destroy", "params": {"target_kind": "creature"}},
        ], "then": [{"type": "destroy", "params": {"target_kind": "creature"}}]})], None)[0]
        assert effect.target_specs == []


class TestIfElse:
    def test_the_true_branch_runs(self) -> None:
        eng = _engine()
        _run(eng, [EffectSpec("if_else", {
            "condition": {"kind": "your_turn"},
            "then": [{"type": "gain_life", "params": {"amount": 7}}],
            "else": [{"type": "gain_life", "params": {"amount": 1}}],
        })])
        assert _life(eng) == 27

    def test_the_false_branch_runs(self) -> None:
        eng = _engine()
        _run(eng, [EffectSpec("if_else", {
            "condition": {"kind": "not_your_turn"},
            "then": [{"type": "gain_life", "params": {"amount": 7}}],
            "else": [{"type": "gain_life", "params": {"amount": 1}}],
        })])
        assert _life(eng) == 21

    def test_an_unanswerable_condition_runs_neither_branch(self) -> None:
        # RULE 701.30d: "if you win the clash, A. Otherwise, B." — with no
        # clash in scope, B must not be the catch-all. A two-valued gate
        # would make `else` fire for every unmodelled condition, which is
        # fail-open; this is why `effect_conditions` is three-valued.
        eng = _engine()
        _run(eng, [EffectSpec("if_else", {
            "condition": {"kind": "clash_won"},
            "then": [{"type": "gain_life", "params": {"amount": 7}}],
            "else": [{"type": "gain_life", "params": {"amount": 1}}],
        })])
        assert _life(eng) == 20

    def test_an_unmodelled_condition_runs_neither_branch(self) -> None:
        eng = _engine()
        _run(eng, [EffectSpec("if_else", {
            "condition": {"kind": "no_such_predicate"},
            "then": [{"type": "gain_life", "params": {"amount": 7}}],
            "else": [{"type": "gain_life", "params": {"amount": 1}}],
        })])
        assert _life(eng) == 20

    def test_a_missing_branch_is_simply_empty(self) -> None:
        eng = _engine()
        _run(eng, [EffectSpec("if_else", {
            "condition": {"kind": "not_your_turn"},
            "then": [{"type": "gain_life", "params": {"amount": 7}}],
        })])
        assert _life(eng) == 20

    def test_the_legacy_flat_condition_spelling_still_works(self) -> None:
        # ENG-36 keeps both spellings legal everywhere; a node is no
        # exception, so a hand-authored entry can use either.
        eng = _engine()
        _run(eng, [EffectSpec("if_else", {
            "condition": {"is_your_turn": True},
            "then": [{"type": "gain_life", "params": {"amount": 7}}],
        })])
        assert _life(eng) == 27


class TestOptional:
    def test_it_asks_before_doing_anything(self) -> None:
        eng = _engine()
        _run(eng, [EffectSpec("optional", {
            "prompt": "Leben dazu?",
            "effects": [{"type": "gain_life", "params": {"amount": 4}}],
        })])
        assert eng.state.pending_choice["kind"] == "composite_optional"
        assert _life(eng) == 20

    def test_yes_runs_the_body(self) -> None:
        eng = _engine()
        _run(eng, [EffectSpec("optional", {
            "effects": [{"type": "gain_life", "params": {"amount": 4}}],
        })])
        eng.rules.resolve_choice("yes")
        assert _life(eng) == 24

    def test_declining_does_nothing(self) -> None:
        # "You may" has no "if you don't" branch — a card printing one spells
        # it as an `if_else` around the same question.
        eng = _engine()
        _run(eng, [EffectSpec("optional", {
            "effects": [{"type": "gain_life", "params": {"amount": 4}}],
        })])
        eng.rules.resolve_choice("decline")
        assert _life(eng) == 20
        assert eng.state.pending_choice is None

    def test_an_empty_body_never_asks(self) -> None:
        eng = _engine()
        _run(eng, [EffectSpec("optional", {"effects": []})])
        assert eng.state.pending_choice is None

    def test_the_question_is_answerable_through_the_client_surface(self) -> None:
        # ENG-35's invariant: `open_choice` refuses a kind no continuation
        # handles, so a node that could strand a live game can't be opened.
        from mtg_analyzer.game import continuations

        assert composition.OptionalEffect.CHOICE_KIND in continuations.CHOICE_HANDLERS


class TestForEach:
    def test_it_runs_once_per_player_in_apnap_order(self) -> None:
        eng = _engine()
        _run(eng, [EffectSpec("for_each", {
            "over": {"players": "each_player"},
            "effects": [{"type": "lose_life",
                         "params": {"amount": 2, "target_kind": "player"}}],
        })])
        assert [p.life for p in eng.state.players] == [18, 18]

    def test_each_opponent_excludes_the_controller(self) -> None:
        eng = _engine()
        source = _creature(eng.state, "p1", "Src")
        _run(eng, [EffectSpec("for_each", {
            "over": {"players": "each_opponent"},
            "effects": [{"type": "lose_life",
                         "params": {"amount": 3, "target_kind": "player"}}],
        })], source=source)
        assert [p.life for p in eng.state.players] == [20, 17]

    def test_an_unknown_player_scope_fails_closed(self) -> None:
        eng = _engine()
        _run(eng, [EffectSpec("for_each", {
            "over": {"players": "everyone_somehow"},
            "effects": [{"type": "lose_life",
                         "params": {"amount": 3, "target_kind": "player"}}],
        })])
        assert [p.life for p in eng.state.players] == [20, 20]

    def test_it_iterates_a_selectors_objects(self) -> None:
        eng = _engine()
        source = _creature(eng.state, "p1", "Src")
        _creature(eng.state, "p1", "A")
        _creature(eng.state, "p1", "B")
        _run(eng, [EffectSpec("for_each", {
            "over": {"selector": "creatures_you_control"},
            "effects": [{"type": "gain_life", "params": {"amount": 1}}],
        })], source=source)
        # Three creatures under p1's control, including the source itself.
        assert _life(eng) == 23

    def test_an_empty_item_list_does_nothing(self) -> None:
        eng = _engine()
        _run(eng, [EffectSpec("for_each", {
            "over": {"targets": True},
            "effects": [{"type": "gain_life", "params": {"amount": 5}}],
        })])
        assert _life(eng) == 20

    def test_the_item_does_not_leak_after_the_loop(self) -> None:
        eng = _engine()
        _run(eng, [EffectSpec("for_each", {
            "over": {"players": "each_player"},
            "effects": [{"type": "gain_life", "params": {"amount": 1}}],
        })])
        assert eng.rules.context.iteration_item is None


class TestBind:
    def test_it_measures_once_and_substitutes_into_the_body(self) -> None:
        eng = _engine()
        source = _creature(eng.state, "p1", "Src", power=3)
        _run(eng, [EffectSpec("bind", {
            "name": "n",
            "amount": {"kind": "characteristic", "characteristic": "power", "of": "source"},
            "effects": [{"type": "gain_life", "params": {"amount": "$n"}}],
        })], source=source)
        assert _life(eng) == 23

    def test_an_unmodelled_measurement_is_zero_not_an_error(self) -> None:
        eng = _engine()
        _run(eng, [EffectSpec("bind", {
            "name": "n",
            "amount": {"kind": "no_such_measurement"},
            "effects": [{"type": "gain_life", "params": {"amount": "$n"}}],
        })])
        assert _life(eng) == 20

    def test_a_plain_int_amount_needs_no_wrapper(self) -> None:
        eng = _engine()
        _run(eng, [EffectSpec("bind", {
            "name": "n", "amount": 6,
            "effects": [{"type": "gain_life", "params": {"amount": "$n"}}],
        })])
        assert _life(eng) == 26

    def test_the_sentinel_is_replaced_at_any_depth(self) -> None:
        eng = _engine()
        substituted = composition.BindEffect._substitute(
            {"a": "$n", "b": [{"c": "$n"}], "d": "$other"}, "$n", 4
        )
        assert substituted == {"a": 4, "b": [{"c": 4}], "d": "$other"}

    def test_nested_binds_do_not_collide(self) -> None:
        eng = _engine()
        _run(eng, [EffectSpec("bind", {
            "name": "outer", "amount": 2,
            "effects": [{"type": "bind", "params": {
                "name": "inner", "amount": 5,
                "effects": [
                    {"type": "gain_life", "params": {"amount": "$outer"}},
                    {"type": "gain_life", "params": {"amount": "$inner"}},
                ],
            }}],
        })])
        assert _life(eng) == 27


class TestNesting:
    def test_a_for_each_body_can_be_an_if_else(self) -> None:
        eng = _engine()
        source = _creature(eng.state, "p1", "Src")
        _run(eng, [EffectSpec("for_each", {
            "over": {"players": "each_opponent"},
            "effects": [{"type": "if_else", "params": {
                "condition": {"kind": "your_turn"},
                "then": [{"type": "lose_life",
                          "params": {"amount": 5, "target_kind": "player"}}],
                "else": [],
            }}],
        })], source=source)
        assert [p.life for p in eng.state.players] == [20, 15]

    def test_a_body_inherits_the_clause_chains_referent(self) -> None:
        # "Destroy target creature. If it was a Bear, gain 4 life." — the
        # `if_else` sits after a targeting clause, so "it" inside the node
        # must still mean what that clause chose.
        eng = _engine()
        source = _creature(eng.state, "p1", "Src")
        victim = _creature(eng.state, "p2", "Bear")
        _run(eng, [
            EffectSpec("destroy", {"target_kind": "creature"}),
            EffectSpec("if_else", {
                "condition": {"kind": "is_subtype", "of": "previous_target",
                              "subtype": "bear"},
                "then": [{"type": "gain_life", "params": {"amount": 4}}],
            }),
        ], source=source, targets=[victim])
        assert _life(eng) == 24


class TestSuspension:
    def test_a_body_choice_parks_the_rest_of_the_outer_list(self) -> None:
        eng = _engine()
        source = _creature(eng.state, "p1", "Src")
        for i in range(2):  # two candidates, so sacrificing is a real choice
            _creature(eng.state, "p1", f"Victim{i}")
        # Only p1 owns creatures, so `each_player` asks exactly one question.
        _run(eng, [
            EffectSpec("seq", {"effects": [
                {"type": "sacrifice",
                 "params": {"count": 1, "what": "creature", "selector": "each_player"}},
            ]}),
            EffectSpec("gain_life", {"amount": 9}),
        ], source=source)
        assert eng.state.pending_choice is not None
        assert _life(eng) == 20, "the sibling must not jump the queue (RULE 608.2)"
        choice = eng.state.pending_choice
        option = choice["options"][0]
        eng.rules.resolve_choice(option.get("id") or option.get("instance_id"))
        eng.resolve_until_stable()
        assert _life(eng) == 29

    def test_a_for_each_asks_once_per_item_in_order(self) -> None:
        eng = _engine()
        for owner in ("p1", "p2"):
            for i in range(2):
                _creature(eng.state, owner, f"{owner}-v{i}")
        _run(eng, [EffectSpec("for_each", {
            "over": {"players": "each_player"},
            "effects": [{"type": "sacrifice",
                         "params": {"count": 1, "what": "creature",
                                    "target_kind": "player"}}],
        })])
        asked = 0
        while eng.state.pending_choice is not None and asked < 5:
            choice = eng.state.pending_choice
            option = choice["options"][0]
            eng.rules.resolve_choice(option.get("id") or option.get("instance_id"))
            eng.resolve_until_stable()
            asked += 1
        assert asked == 2, "one prompt per player, neither overwritten"
        assert len(eng.state.battlefield) == 2


class TestOutOfOrderResumptionIsFixed:
    """A pre-existing RULE 608.2 ordering bug ENG-37 had to fix first.

    `SacrificeEffect`/`ConniveEffect`/`PopulateEffect` all suspend a loop of
    their own by pushing a frame from inside `apply`, and
    `resume_deferred_effects` pops from the top — so the enclosing list's
    remainder, appended *afterwards*, used to resume **first** and run the
    rest of the resolution while that loop was still half-finished. Every
    composition node has the same shape, so this had to be right before the
    nodes could rely on it.
    """

    def test_a_sibling_waits_for_a_per_player_loop_to_finish(self) -> None:
        eng = _engine()
        for owner in ("p1", "p2"):
            for i in range(2):
                _creature(eng.state, owner, f"{owner}-v{i}")
        from mtg_analyzer.game.effects.core import GainLifeEffect, SacrificeEffect

        context = GameContext(eng.state, eng.rules)
        _apply_effects_partitioned(
            [SacrificeEffect(count=1, what="creature", selector="each_player"),
             GainLifeEffect(amount=5)],
            context, None, None,
        )
        assert _life(eng) == 20, "life gain ran before the second player sacrificed"
        choice = eng.state.pending_choice
        option = choice["options"][0]
        eng.rules.resolve_choice(option.get("id") or option.get("instance_id"))
        eng.resolve_until_stable()
        assert _life(eng) == 20, "still one player to go"
        choice = eng.state.pending_choice
        option = choice["options"][0]
        eng.rules.resolve_choice(option.get("id") or option.get("instance_id"))
        eng.resolve_until_stable()
        assert _life(eng) == 25
        assert not eng.state.deferred_effects


class TestRegistryAndClassification:
    def test_every_operator_has_a_registered_node(self) -> None:
        for operator in isa.OPERATORS:
            names = [
                name for name, entry in isa.EFFECT_TYPES.items()
                if entry.classification is isa.Classification.COMPOSITION
                and entry.operator == operator
            ]
            assert len(names) == 1, operator
            assert EffectRegistry.is_registered(names[0])

    def test_the_parsers_node_list_matches_the_classification(self) -> None:
        # `parser/oracle/spec.py` must not import `game/` (docs/09), so it
        # names the node types itself to know whose ``params`` may carry a
        # ``condition``. That copy is only safe while something compares it.
        from mtg_analyzer.parser.oracle.spec import _COMPOSITION_EFFECT_TYPES

        classified = {
            name for name, entry in isa.EFFECT_TYPES.items()
            if entry.classification is isa.Classification.COMPOSITION
        }
        assert _COMPOSITION_EFFECT_TYPES == classified

    def test_a_node_is_not_classified_as_a_fusion(self) -> None:
        # A composition node is what a fusion decomposes *into*; classifying
        # one as a fusion would make the backlog count itself.
        for name in ("seq", "if_else", "optional", "for_each", "bind"):
            assert isa.classification_of(name) is isa.Classification.COMPOSITION


class TestValidation:
    def test_a_nested_body_is_validated_at_every_depth(self) -> None:
        # The ENG-37 security half: `validate()` recurses structurally, so a
        # body one level down is clamped and whitelisted like any other spec.
        spec = AbilitySpec(ability_kind="spell_effect", effects=[
            EffectSpec("seq", {"effects": [
                {"type": "draw", "params": {"count": 10 ** 9}},
            ]}),
        ])
        spec.validate()
        assert spec.effects[0].params["effects"][0]["params"]["count"] < 10 ** 9

    def test_an_unregistered_body_type_is_refused_at_bind_time(self) -> None:
        from mtg_analyzer.game.binding.core import BindError

        with pytest.raises(BindError):
            build_effects([EffectSpec("seq", {"effects": [
                {"type": "definitely_not_registered", "params": {}},
            ]})], None)[0].target_specs

    def test_a_structured_condition_on_a_node_validates(self) -> None:
        spec = AbilitySpec(ability_kind="spell_effect", effects=[
            EffectSpec("if_else", {
                "condition": {"kind": "kicked", "min": 1},
                "then": [{"type": "draw", "params": {"count": 1}}],
            }),
        ])
        spec.validate()

    def test_a_malformed_node_condition_is_refused(self) -> None:
        spec = AbilitySpec(ability_kind="spell_effect", effects=[
            EffectSpec("if_else", {
                "condition": {"kind": "kicked", "min": True},
                "then": [{"type": "draw", "params": {"count": 1}}],
            }),
        ])
        with pytest.raises(SpecValidationError):
            spec.validate()

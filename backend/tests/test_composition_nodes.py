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
* RULE 601.2c: only a node whose body definitely runs in full — ``seq``,
  ``optional``, ``bind`` — may announce its body's targets.

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

    @pytest.mark.parametrize("node", ["if_else", "for_each"])
    def test_the_other_nodes_announce_nothing(self, node: str) -> None:
        # Neither knows at announce time *what* will run — which branch
        # (`if_else`), how many times (`for_each`) — so neither may claim a
        # RULE 115 requirement of its own.
        effect = build_effects([EffectSpec(node, {"effects": [
            {"type": "destroy", "params": {"target_kind": "creature"}},
        ], "then": [{"type": "destroy", "params": {"target_kind": "creature"}}]})], None)[0]
        assert effect.target_specs == []

    def test_bind_announces_its_bodys_targets(self) -> None:
        # A `bind` runs its body exactly once, unconditionally — so, like
        # `seq`/`optional` and unlike `if_else`/`for_each`, RULE 601.2c lets
        # it surface the body's requirements. "~ deals X damage to any
        # target. You gain life … but not more than the target's toughness"
        # (Drain Life) is a `bind` whose body's `damage` clause targets.
        effect = build_effects([EffectSpec("bind", {
            "name": "cap",
            "amount": {"kind": "target_defense", "of": "target"},
            "effects": [
                {"type": "damage", "params": {"amount": 1, "target_kind": "any"}},
                {"type": "gain_life", "params": {"amount": "$cap"}},
            ],
        })], None)[0]
        assert [spec.kind for spec in effect.target_specs] == ["any"]

    def test_optional_does_announce_its_bodys_targets(self) -> None:
        # PAR-62 corrected this: `optional` was grouped with the three above,
        # but it belongs with `seq`. Its body is fixed and singular — the only
        # open question is *whether* it runs, and RULE 601.2b answers that at
        # resolution, long after RULE 601.2c fixed the targets on
        # announcement. "When you cycle this card, you may tap target
        # creature." (Choking Tethers) targets when the trigger goes on the
        # stack. Without this the card parsed as MODELED and then resolved to
        # nothing at all.
        effect = build_effects([EffectSpec("optional", {"effects": [
            {"type": "tap", "params": {"target_kind": "creature"}},
        ]})], None)[0]
        assert [spec.kind for spec in effect.target_specs] == ["creature"]


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

    def test_unattach_rider_acts_on_the_former_host(self) -> None:
        """ENG-37 B6: an operand can follow an attachment relation across a
        mutation, so Akiri is composition rather than a welded effect."""
        eng = _engine()
        host = _creature(eng.state, name="Host")
        equipment = GameObject(
            Card(id="equip", name="Equipment", type_line="Artifact — Equipment"),
            owner_id="p1", zone=Zone.BATTLEFIELD,
        )
        equipment.attached_to = host.instance_id
        eng.state.add_to_battlefield(equipment)

        _run(eng, [EffectSpec("optional", {"effects": [
            {"type": "unattach", "params": {
                "target_kind": "attached_equipment_you_control",
            }},
            {"type": "tap", "params": {
                "target_kind": None,
                "target_operand": {"of": "previous_target", "as": "host"},
            }},
            {"type": "pump", "params": {
                "keywords": ["indestructible"], "target_kind": None,
                "target_operand": {"of": "previous_target", "as": "host"},
            }},
        ]})], targets=[equipment])
        eng.rules.resolve_choice("yes")

        assert equipment.attached_to is None
        assert host.tapped is True
        assert "indestructible" in host.temp_keywords


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


class TestB4SharedTargetRetirements:
    """ENG-37 B4: the fused effect types whose only reason to exist was
    docs/11 §5's "at most one targeting effect per ability" — a `seq` shares
    one resolved target across its whole body (the first clause carries the
    RULE 115 requirement; the rest read `GameContext.previous_targets` via
    their own ``previous_subject`` pronoun), so no welded type is needed.
    """

    def test_target_player_draw_lose_life_is_one_announced_target(self) -> None:
        # Retires ``target_player_draw_lose_life`` (Sign in Blood).
        eng = _engine()
        p2 = eng.state.player_by_id("p2")
        for _ in range(3):
            p2.library.append(GameObject(
                Card(id="f", name="Filler", type_line="Creature", is_creature=True,
                     power=1, toughness=1),
                owner_id="p2", zone=Zone.LIBRARY,
            ))
        hand0, life0 = len(p2.hand), p2.life

        effects = build_effects([EffectSpec("seq", {"effects": [
            {"type": "draw", "params": {"count": 2, "target_kind": "player"}},
            {"type": "lose_life", "params": {"amount": 2, "previous_subject": True}},
        ]})], None)
        assert [ts.kind for e in effects for ts in e.target_specs] == ["player"]

        context = GameContext(eng.state, eng.rules)
        _apply_effects_partitioned(effects, context, [p2], None)
        assert len(p2.hand) - hand0 == 2
        assert p2.life - life0 == -2

    def test_add_counter_first_strike_shares_the_creature(self) -> None:
        # Retires ``add_counter_first_strike`` (The Wandering Emperor +1).
        from mtg_analyzer.game import combat

        eng = _engine()
        bear = _creature(eng.state)
        effects = build_effects([
            EffectSpec("add_counters", {
                "kind": "+1/+1", "amount": 1, "target_kind": "creature", "optional": True,
            }),
            EffectSpec("grant_until", {
                "duration": "end_of_turn", "previous_subject": True,
                "static": {"type": "grant_keyword", "params": {"keywords": ["first_strike"]}},
            }),
        ], bear)
        assert [ts.kind for e in effects for ts in e.target_specs] == ["creature"]
        assert [ts.optional for e in effects for ts in e.target_specs] == [True]

        context = GameContext(eng.state, eng.rules)
        _apply_effects_partitioned(effects, context, [bear], None)
        eng.rules.check_state_based_actions()
        assert bear.counters.get("+1/+1") == 1
        assert bear.power == bear.card.power + 1
        assert combat.has(bear, "first_strike")

    def test_counter_untap_grant_keyword_shares_the_creature(self) -> None:
        # Retires ``counter_untap_grant_keyword`` (Tyvar Kell +1): counter,
        # untap "it", "it" gains deathtouch — all one chosen creature.
        from mtg_analyzer.game import combat

        eng = _engine()
        elf = _creature(eng.state, name="Elf", power=1, toughness=1)
        elf.card.type_line = "Creature — Elf"
        eng.rules.set_tapped(elf, tapped=True)

        effects = build_effects([
            EffectSpec("add_counters", {
                "kind": "+1/+1", "amount": 1, "target_kind": "creature",
                "optional": True, "creature_filter": {"subtype": "Elf"},
            }),
            EffectSpec("tap", {"untap": True, "previous_subject": True}),
            EffectSpec("grant_until", {
                "duration": "end_of_turn", "previous_subject": True,
                "static": {"type": "grant_keyword", "params": {"keywords": ["deathtouch"]}},
            }),
        ], elf)
        assert [ts.kind for e in effects for ts in e.target_specs] == ["creature"]

        context = GameContext(eng.state, eng.rules)
        _apply_effects_partitioned(effects, context, [elf], None)
        eng.rules.check_state_based_actions()
        assert elf.counters.get("+1/+1") == 1
        assert elf.tapped is False
        assert combat.has(elf, "deathtouch")

    def test_a_declined_optional_target_no_ops_the_whole_body(self) -> None:
        # "up to one target" declined → nothing to carry forward; the
        # untap/grant clauses must quietly do nothing, not raise.
        eng = _engine()
        effects = build_effects([
            EffectSpec("add_counters", {
                "kind": "+1/+1", "amount": 1, "target_kind": "creature", "optional": True,
            }),
            EffectSpec("tap", {"untap": True, "previous_subject": True}),
            EffectSpec("grant_until", {
                "duration": "end_of_turn", "previous_subject": True,
                "static": {"type": "grant_keyword", "params": {"keywords": ["deathtouch"]}},
            }),
        ], None)
        context = GameContext(eng.state, eng.rules)
        _apply_effects_partitioned(effects, context, [], None)
        assert eng.state.floating_statics == []

    def test_the_three_fused_types_are_gone_from_the_registry(self) -> None:
        for name in (
            "target_player_draw_lose_life",
            "add_counter_first_strike",
            "counter_untap_grant_keyword",
        ):
            assert not EffectRegistry.is_registered(name)
            assert name not in isa.EFFECT_TYPES


class TestB4BoostedPowerRetirement:
    """ENG-37 batch 7: `counter_then_fightlike_damage` (Archdruid's Charm
    mode 2) retired to `[add_counters, damage_equal_to_power{previous_target}]`
    once `AddCountersEffect.apply` started recomputing (RULE 613.1) like every
    other P/T one-shot — so the damage clause reads the *boosted* power.
    """

    def test_damage_reads_the_boosted_power_after_the_counter(self) -> None:
        eng = _engine()
        mine = _creature(eng.state, owner="p1", name="Mine", power=1, toughness=1)
        theirs = _creature(eng.state, owner="p2", name="Theirs", power=3, toughness=3)
        eng.rules.check_state_based_actions()

        effects = build_effects([
            EffectSpec("add_counters", {
                "kind": "+1/+1", "amount": 1, "target_kind": "creature_you_control",
            }),
            EffectSpec("damage_equal_to_power", {
                "dealer_kind": "previous_target",
                "target_kind": "creature_you_dont_control",
            }),
        ], mine)
        assert [ts.kind for e in effects for ts in e.target_specs] == [
            "creature_you_control", "creature_you_dont_control",
        ]

        context = GameContext(eng.state, eng.rules)
        # The modal / spell resolution partitions the two requirements — a
        # flat list would hand the recipient iterator `mine` first.
        _apply_effects_partitioned(effects, context, [mine, theirs], [[mine], [theirs]])

        assert mine.counters.get("+1/+1") == 1
        assert theirs.damage_marked == 2  # 1 printed + 1 counter, not 1

    def test_add_counters_recomputes_so_a_later_clause_sees_it(self) -> None:
        eng = _engine()
        bear = _creature(eng.state, power=2, toughness=2)
        eng.rules.check_state_based_actions()
        assert bear.power == 2

        context = GameContext(eng.state, eng.rules)
        _apply_effects_partitioned(
            build_effects([EffectSpec("add_counters", {
                "kind": "+1/+1", "amount": 3, "target_kind": "creature",
            })], bear),
            context, [bear], None,
        )
        # No SBA pass in between — the effect recomputed on its own.
        assert bear.power == 5

    def test_counter_then_fightlike_damage_is_gone(self) -> None:
        assert not EffectRegistry.is_registered("counter_then_fightlike_damage")
        assert "counter_then_fightlike_damage" not in isa.EFFECT_TYPES


class TestBindDrainCap:
    """ENG-37 batch 8: the fused `damage_and_drain_capped` (Drain Life) retired
    to a `bind` — its `amount` measures the target's `target_defense` (life /
    loyalty / toughness), clamped to `[0, X]`, *before* the body deals the
    damage; the body then gains `$cap`.
    """

    def test_bind_measures_the_target_before_the_body_runs(self) -> None:
        eng = _engine()
        victim = _creature(eng.state, owner="p2", name="Victim", power=1, toughness=2)
        eng.rules.check_state_based_actions()
        before = _life(eng)

        effects = build_effects([EffectSpec("bind", {
            "name": "cap",
            "amount": {"kind": "target_defense", "of": "target", "minimum": 0, "maximum": 5},
            "effects": [
                {"type": "damage", "params": {"amount": 5, "target_kind": "any"}},
                {"type": "gain_life", "params": {"amount": "$cap"}},
            ],
        })], None)
        assert [ts.kind for e in effects for ts in e.target_specs] == ["any"]

        _apply_effects_partitioned(effects, GameContext(eng.state, eng.rules), [victim], None)
        # 5 damage dealt, but life gained is the pre-damage toughness (2).
        assert _life(eng) - before == 2
        assert victim.damage_marked == 5
        eng.rules.check_state_based_actions()
        assert victim not in eng.state.battlefield  # 5 >= 2

    def test_bind_amount_maximum_clamps_to_x(self) -> None:
        eng = _engine()
        p2 = eng.state.player_by_id("p2")
        p2.life = 40
        before = _life(eng)

        effects = build_effects([EffectSpec("bind", {
            "name": "cap",
            "amount": {"kind": "target_defense", "of": "target", "minimum": 0, "maximum": 3},
            "effects": [
                {"type": "damage", "params": {"amount": 3, "target_kind": "any"}},
                {"type": "gain_life", "params": {"amount": "$cap"}},
            ],
        })], None)
        _apply_effects_partitioned(effects, GameContext(eng.state, eng.rules), [p2], None)
        # cap would be 40 (life), clamped to X=3.
        assert _life(eng) - before == 3

    def test_resolve_x_substitutes_into_a_bind_body_and_amount(self) -> None:
        # `_substitute_x` never reaches a still-serialized node body; the
        # composition module does it from the source's announced {X}.
        spell = Card(id="s", name="Sp", type_line="Sorcery", is_sorcery=True)
        src = GameObject(spell, owner_id="p1", zone=Zone.STACK)
        src.x_paid = 4

        eng = _engine()
        p2 = eng.state.player_by_id("p2")
        p2.life = 40
        before = _life(eng)
        effects = build_effects([EffectSpec("bind", {
            "name": "cap",
            "amount": {"kind": "target_defense", "of": "target", "minimum": 0, "maximum": "x"},
            "effects": [
                {"type": "damage", "params": {"amount": "x", "target_kind": "any"}},
                {"type": "gain_life", "params": {"amount": "$cap"}},
            ],
        })], src)
        _apply_effects_partitioned(effects, GameContext(eng.state, eng.rules), [p2], None, source=src)
        assert p2.life == 36          # 4 damage
        assert _life(eng) - before == 4  # cap clamped to X=4

    def test_damage_and_drain_capped_is_gone(self) -> None:
        assert not EffectRegistry.is_registered("damage_and_drain_capped")
        assert "damage_and_drain_capped" not in isa.EFFECT_TYPES


class TestB5RevealReferent:
    """ENG-37 B5: `reveal_top` (RULE 701.20) stashes the top card as
    `GameContext.revealed_card`; a following `if_else`/`bind` reads it as the
    `of: "revealed"` referent; `put_revealed_card` moves it (RULE 121.4
    non-draw for "hand"). Retires the deterministic `reveal_top_*` fusions.
    """

    def _lib(self, eng, name, type_line, owner="p1", **card_kw):
        obj = GameObject(
            Card(id=name, name=name, type_line=type_line, **card_kw),
            owner_id=owner, zone=Zone.LIBRARY,
        )
        eng.state.player_by_id(owner).library.append(obj)
        return obj

    def test_reveal_then_if_else_land_goes_to_hand(self) -> None:
        # Goblin-Guide shape: land -> hand, non-land -> left on top.
        eng = _engine()
        p1 = eng.state.player_by_id("p1")
        land = self._lib(eng, "Forest", "Basic Land — Forest", is_land=True)
        specs = [EffectSpec("seq", {"effects": [
            {"type": "reveal_top", "params": {"whose": "you"}},
            {"type": "if_else", "params": {
                "condition": {"kind": "is_card_type", "of": "revealed", "card_type": "land"},
                "then": [{"type": "put_revealed_card", "params": {"destination": "hand"}}],
                "else": [],
            }},
        ]})]
        _run(eng, specs)
        assert land in p1.hand
        # a nested resolution must not inherit the stashed card
        assert eng.rules.context.revealed_card is None

        eng2 = _engine()
        p1b = eng2.state.player_by_id("p1")
        inst = self._lib(eng2, "Bolt", "Instant", is_instant=True)
        _run(eng2, specs)
        assert inst in p1b.library and not p1b.hand

    def test_reveal_then_bind_measures_the_revealed_cards_mana_value(self) -> None:
        # Dark Confidant shape.
        eng = _engine()
        p1 = eng.state.player_by_id("p1")
        p1.life = 20
        card = self._lib(eng, "Bob Hit", "Creature — Human Wizard", is_creature=True,
                         converted_mana_cost=3, power=2, toughness=1)
        _run(eng, [EffectSpec("seq", {"effects": [
            {"type": "reveal_top", "params": {"whose": "you"}},
            {"type": "bind", "params": {
                "name": "mv",
                "amount": {"kind": "characteristic", "characteristic": "mana_value",
                           "of": "revealed"},
                "effects": [
                    {"type": "put_revealed_card", "params": {"destination": "hand"}},
                    {"type": "lose_life", "params": {"amount": "$mv"}},
                ],
            }},
        ]})])
        assert card in p1.hand
        assert p1.life == 17
        # RULE 121.4 — not a draw
        assert eng.state.cards_drawn_this_turn.get("p1", 0) == 0

    def test_reveal_then_if_else_land_to_battlefield_else_draw(self) -> None:
        # Thrasios shape.
        specs = [EffectSpec("seq", {"effects": [
            {"type": "reveal_top", "params": {"whose": "you"}},
            {"type": "if_else", "params": {
                "condition": {"kind": "is_card_type", "of": "revealed", "card_type": "land"},
                "then": [{"type": "put_revealed_card",
                          "params": {"destination": "battlefield_tapped"}}],
                "else": [{"type": "draw", "params": {"count": 1}}],
            }},
        ]})]

        eng = _engine()
        p1 = eng.state.player_by_id("p1")
        land = self._lib(eng, "Island", "Basic Land — Island", is_land=True)
        _run(eng, specs)
        assert land in eng.state.battlefield and land.tapped

        eng2 = _engine()
        p2 = eng2.state.player_by_id("p1")
        self._lib(eng2, "Filler1", "Instant", is_instant=True)
        self._lib(eng2, "Filler2", "Instant", is_instant=True)  # this is top
        h0 = len(p2.hand)
        _run(eng2, specs)
        assert len(p2.hand) - h0 == 1

    def test_reveal_then_maybe_battlefield_gates_on_land_or_cheap_creature(self) -> None:
        # Nissa's 0: `any(land, all(creature, mv <= source loyalty))` then an
        # `optional` put_revealed_card. The `revealed` referent must survive
        # the `composite_optional` pause.
        specs = [EffectSpec("seq", {"effects": [
            {"type": "reveal_top", "params": {"whose": "you"}},
            {"type": "if_else", "params": {
                "condition": {"kind": "any", "conditions": [
                    {"kind": "is_card_type", "of": "revealed", "card_type": "land"},
                    {"kind": "all", "conditions": [
                        {"kind": "is_card_type", "of": "revealed", "card_type": "creature"},
                        {"kind": "amount_compare", "op": "le",
                         "left": {"kind": "characteristic", "characteristic": "mana_value",
                                  "of": "revealed"},
                         "right": {"kind": "counters", "counter": "loyalty", "of": "source"}},
                    ]},
                ]},
                "then": [{"type": "optional", "params": {
                    "effects": [{"type": "put_revealed_card",
                                 "params": {"destination": "battlefield"}}],
                }}],
                "else": [],
            }},
        ]})]

        # a cheap creature (mv 2) with source loyalty 3 -> offered, accept
        eng = _engine()
        src = _creature(eng.state, name="Nissa", power=0, toughness=1)
        src.counters["loyalty"] = 3
        p1 = eng.state.player_by_id("p1")
        cheap = GameObject(
            Card(id="c2", name="Elf", type_line="Creature — Elf", is_creature=True,
                 converted_mana_cost=2, power=1, toughness=1),
            owner_id="p1", zone=Zone.LIBRARY,
        )
        p1.library.append(cheap)
        _run(eng, specs, source=src)
        assert eng.state.pending_choice["kind"] == "composite_optional"
        eng.rules.resolve_choice("yes")
        assert cheap in eng.state.battlefield

        # an expensive creature (mv 6) with source loyalty 3 -> not offered
        eng2 = _engine()
        src2 = _creature(eng2.state, name="Nissa", power=0, toughness=1)
        src2.counters["loyalty"] = 3
        big = GameObject(
            Card(id="c6", name="Titan", type_line="Creature — Giant", is_creature=True,
                 converted_mana_cost=6, power=6, toughness=6),
            owner_id="p1", zone=Zone.LIBRARY,
        )
        eng2.state.player_by_id("p1").library.append(big)
        _run(eng2, specs, source=src2)
        assert eng2.state.pending_choice is None
        assert big in eng2.state.player_by_id("p1").library

    def test_the_reveal_fusions_are_gone(self) -> None:
        for name in (
            "reveal_top_then_take_and_lose_life",
            "reveal_top_then_land_battlefield_or_draw",
            "reveal_top_conditional_to_hand",
            "reveal_top_then_maybe_battlefield_if_land_or_cheap_creature",
            "reveal_top_then_counter_if_mv_match",
            "reveal_top_then_free_cast_if_mv_match",
        ):
            assert not EffectRegistry.is_registered(name)
            assert name not in isa.EFFECT_TYPES


class TestB5BindOverDigUntil:
    """ENG-37 B5: `exile_then_reveal_greater_mana_value` (Lukka, Coppercoat
    Outcast's -2) retired to a `bind` — the dig's mana-value floor is the
    exiled target's own mana value + 1 (RULE 608.2, measured before the
    body's `exile`), substituted into a `dig_until` `criteria`.
    """

    def _lib_creature(self, eng, name, mv, owner="p1"):
        obj = GameObject(
            Card(id=name, name=name, type_line="Creature — Beast", is_creature=True,
                 converted_mana_cost=mv, power=2, toughness=2),
            owner_id=owner, zone=Zone.LIBRARY,
        )
        eng.state.player_by_id(owner).library.append(obj)
        return obj

    def test_floor_is_the_targets_mana_value_plus_one(self) -> None:
        eng = _engine()
        p1 = eng.state.player_by_id("p1")
        target = _creature(eng.state, name="T", power=2, toughness=2)
        target.card.converted_mana_cost = 2  # floor becomes 3
        small = self._lib_creature(eng, "SmallMV2", 2)
        hit = self._lib_creature(eng, "HitMV4", 4)   # top of library, mv 4 >= 3

        specs = [EffectSpec("bind", {
            "name": "floor",
            "amount": {"kind": "characteristic", "characteristic": "mana_value",
                       "of": "target", "plus": 1},
            "effects": [
                {"type": "exile", "params": {"target_kind": "creature_you_control"}},
                {"type": "dig_until", "params": {
                    "criteria": {"type": "Creature", "min_mana_value": "$floor"},
                    "hit_destination": "battlefield",
                    "rest_destination": "library_bottom_random",
                }},
            ],
        })]
        assert [ts.kind for e in build_effects(specs, target) for ts in e.target_specs] == [
            "creature_you_control",
        ]

        _apply_effects_partitioned(
            build_effects(specs, target), GameContext(eng.state, eng.rules),
            [target], None, source=target,
        )
        assert target.zone == Zone.EXILE
        assert hit in eng.state.battlefield
        assert small not in eng.state.battlefield  # mv 2 < floor 3

    def test_exile_then_reveal_greater_mana_value_is_gone(self) -> None:
        assert not EffectRegistry.is_registered("exile_then_reveal_greater_mana_value")
        assert "exile_then_reveal_greater_mana_value" not in isa.EFFECT_TYPES


class TestB6ConditionalCastFromExile:
    """ENG-37 B6: `exile_top_then_grant_conditional_cast` (Lukka, Coppercoat
    Outcast's +1) retired to `seq([exile_top_of_library, grant_conditional_
    cast_from_exile])` — the grant half reads the just-exiled batch off
    `GameContext.created_objects` (the "exiled this way" referent the exile
    clause already populates) and stamps a standing `exile_cast_condition`
    per creature card.
    """

    _COND = {
        "kind": "control_count",
        "selector": "planeswalkers_you_control_of_type_lukka",
        "min": 1,
    }

    def _specs(self, count: int = 3):
        return [EffectSpec("seq", {"effects": [
            {"type": "exile_top_of_library", "params": {"count": count}},
            {"type": "grant_conditional_cast_from_exile",
             "params": {"condition": self._COND}},
        ]})]

    def test_only_creature_cards_among_the_exiled_batch_get_the_grant(self) -> None:
        eng = _engine()
        p1 = eng.state.player_by_id("p1")
        creo1 = GameObject(Card(id="Creo1", name="Creo1", type_line="Creature",
                                is_creature=True), owner_id="p1", zone=Zone.LIBRARY)
        creo2 = GameObject(Card(id="Creo2", name="Creo2", type_line="Creature",
                                is_creature=True), owner_id="p1", zone=Zone.LIBRARY)
        sorc = GameObject(Card(id="Sorc1", name="Sorc1", type_line="Sorcery",
                               is_sorcery=True), owner_id="p1", zone=Zone.LIBRARY)
        for o in (creo1, creo2, sorc):   # sorc ends up on top (list end)
            p1.library.append(o)
        src = _creature(eng.state, name="Lukka", power=0, toughness=1)

        _run(eng, self._specs(3), source=src)

        assert {creo1, creo2, sorc}.issubset(set(p1.exile))
        cond = eng.state.exile_cast_condition
        assert cond.get(creo1.instance_id) == ("p1", self._COND)
        assert cond.get(creo2.instance_id) == ("p1", self._COND)
        assert sorc.instance_id not in cond          # noncreature: no grant

    def test_no_creatures_exiled_is_a_clean_no_op(self) -> None:
        eng = _engine()
        p1 = eng.state.player_by_id("p1")
        for i in range(3):
            p1.library.append(GameObject(
                Card(id=f"S{i}", name=f"S{i}", type_line="Sorcery", is_sorcery=True),
                owner_id="p1", zone=Zone.LIBRARY,
            ))
        src = _creature(eng.state, name="Lukka", power=0, toughness=1)

        _run(eng, self._specs(3), source=src)
        assert eng.state.exile_cast_condition == {}
        assert len(p1.exile) == 3

    def test_the_fused_type_is_gone(self) -> None:
        assert not EffectRegistry.is_registered("exile_top_then_grant_conditional_cast")
        assert "exile_top_then_grant_conditional_cast" not in isa.EFFECT_TYPES
        assert EffectRegistry.is_registered("grant_conditional_cast_from_exile")

    def test_the_catalogue_entry_still_binds(self) -> None:
        from mtg_analyzer.game import ability_catalogue as ac

        card = Card(id="LK", name="Lukka, Coppercoat Outcast",
                    type_line="Legendary Planeswalker — Lukka")
        specs = ac.specs_for(card)
        assert specs
        for spec in specs:
            build_effects(list(spec.effects), None)


class TestB6CorpseDanceRetirement:
    """ENG-37 B6: `return_top_graveyard_creature_with_haste` (Corpse Dance)
    retired to `seq([return_from_graveyard{positional_top_creature, haste},
    create_delayed_trigger{capture: "previous_or_self", ...}])`. The return
    surfaces the creature onto `created_objects`; the delayed trigger's
    `capture` bakes that same object into its "exile it at the next end
    step" body.
    """

    def _specs(self):
        return [EffectSpec("seq", {"effects": [
            {"type": "return_from_graveyard",
             "params": {"positional_top_creature": True, "haste": True}},
            {"type": "if_else", "params": {
                "condition": {"kind": "is_card_type", "of": "previous_target",
                              "card_type": "creature"},
                "then": [{"type": "create_delayed_trigger", "params": {
                    "step": "end", "scope": "any", "capture": "previous_or_self",
                    "effects": [{"type": "exile", "params": {"target_kind": None}}],
                    "description": "Corpse Dance",
                }}],
            }},
        ]})]

    def _grave(self, eng, name, is_creature=True):
        pt = {"power": 2, "toughness": 2} if is_creature else {}
        obj = GameObject(
            Card(id=name, name=name,
                 type_line="Creature — Zombie" if is_creature else "Sorcery",
                 is_creature=is_creature, is_sorcery=not is_creature, **pt),
            owner_id="p1", zone=Zone.GRAVEYARD,
        )
        eng.state.player_by_id("p1").graveyard.append(obj)
        return obj

    def test_returns_the_top_creature_with_haste_and_arms_the_delayed_exile(self) -> None:
        eng = _engine()
        src = _creature(eng.state, name="Corpse Dance", power=0, toughness=1)
        junk = self._grave(eng, "Junk", is_creature=False)
        old = self._grave(eng, "OldZombie")
        top = self._grave(eng, "TopZombie")   # most recently added = "top"

        _apply_effects_partitioned(
            build_effects(self._specs(), src), GameContext(eng.state, eng.rules),
            None, None, source=src,
        )
        eng.recompute_continuous_effects()

        assert top in eng.state.battlefield
        assert old.zone == Zone.GRAVEYARD and junk.zone == Zone.GRAVEYARD
        assert "haste" in top.temp_keywords or "haste" in top.granted_keywords

        dts = eng.state.delayed_triggers
        assert len(dts) == 1 and dts[0].step == "end" and dts[0].scope == "any"
        # the delayed exile names the returned creature, not a fresh target
        assert any(getattr(e, "target", None) is top for e in dts[0].effects)

    def test_empty_graveyard_is_a_no_op(self) -> None:
        eng = _engine()
        src = _creature(eng.state, name="Corpse Dance", power=0, toughness=1)
        self._grave(eng, "OnlyJunk", is_creature=False)

        _apply_effects_partitioned(
            build_effects(self._specs(), src), GameContext(eng.state, eng.rules),
            None, None, source=src,
        )
        assert not eng.state.delayed_triggers
        assert len(eng.state.player_by_id("p1").graveyard) == 1

    def test_the_fused_type_is_gone(self) -> None:
        assert not EffectRegistry.is_registered("return_top_graveyard_creature_with_haste")
        assert "return_top_graveyard_creature_with_haste" not in isa.EFFECT_TYPES

    def test_the_catalogue_entry_still_binds(self) -> None:
        from mtg_analyzer.game import ability_catalogue as ac

        card = Card(id="CD", name="Corpse Dance", type_line="Instant", is_instant=True)
        specs = ac.specs_for(card)
        assert specs
        for spec in specs:
            build_effects(list(spec.effects), None)


class TestB7WheelFamilyRetirements:
    """ENG-37 B7: the fused `wheel` / `wheel_of_fortune` / `windfall` types
    retired. Each printed line is now `seq`/`bind` over a mass
    `shuffle_hand_and_graveyard_into_library` or `discard`
    (``scope="each_player"``, ``whole_hand=True``) plus a mass `draw`
    (``selector="each_player"``). Windfall's draw count is a `bind` over
    ``resource: hand_size`` with ``aggregate: max``, taken before the discard.
    """

    def _stock_library(self, eng, player_id: str, n: int) -> None:
        p = eng.state.player_by_id(player_id)
        for i in range(n):
            p.library.append(GameObject(
                Card(id=f"Lib{player_id}{i}", name=f"Lib{player_id}{i}",
                     type_line="Creature", is_creature=True),
                owner_id=player_id, zone=Zone.LIBRARY,
            ))

    def _fill_hand(self, eng, player_id: str, n: int) -> None:
        p = eng.state.player_by_id(player_id)
        for i in range(n):
            p.hand.append(GameObject(
                Card(id=f"H{player_id}{i}", name=f"H{player_id}{i}",
                     type_line="Land", is_land=True),
                owner_id=player_id, zone=Zone.HAND,
            ))

    def test_wheel_of_fortune_each_player_discards_hand_then_draws_seven(self) -> None:
        eng = _engine()
        self._stock_library(eng, "p1", 10)
        self._stock_library(eng, "p2", 10)
        self._fill_hand(eng, "p1", 2)
        self._fill_hand(eng, "p2", 5)

        _run(eng, [EffectSpec("seq", {"effects": [
            {"type": "discard", "params": {"scope": "each_player", "whole_hand": True}},
            {"type": "draw", "params": {"selector": "each_player", "count": 7}},
        ]})])

        assert len(eng.state.player_by_id("p1").hand) == 7
        assert len(eng.state.player_by_id("p2").hand) == 7
        assert len(eng.state.player_by_id("p1").graveyard) == 2
        assert len(eng.state.player_by_id("p2").graveyard) == 5

    def test_windfall_draws_the_greatest_pre_discard_hand_size(self) -> None:
        eng = _engine()
        self._stock_library(eng, "p1", 10)
        self._stock_library(eng, "p2", 10)
        self._fill_hand(eng, "p1", 3)
        self._fill_hand(eng, "p2", 1)

        _run(eng, [EffectSpec("bind", {
            "name": "n",
            "amount": {"kind": "resource", "resource": "hand_size",
                       "aggregate": "max", "scope": "each_player"},
            "effects": [
                {"type": "discard",
                 "params": {"scope": "each_player", "whole_hand": True}},
                {"type": "draw",
                 "params": {"selector": "each_player", "count": "$n"}},
            ],
        })])

        # greatest hand size when the bind measured was 3 -> everyone draws 3,
        # so the player who only discarded 1 still nets +2.
        assert len(eng.state.player_by_id("p1").hand) == 3
        assert len(eng.state.player_by_id("p2").hand) == 3

    def test_timetwister_shuffles_hand_and_graveyard_then_draws_seven(self) -> None:
        eng = _engine()
        self._stock_library(eng, "p1", 10)
        self._stock_library(eng, "p2", 10)
        self._fill_hand(eng, "p1", 1)
        self._fill_hand(eng, "p2", 1)
        p1 = eng.state.player_by_id("p1")
        gy = GameObject(
            Card(id="GYcard", name="GYcard", type_line="Creature", is_creature=True),
            owner_id="p1", zone=Zone.GRAVEYARD,
        )
        p1.graveyard.append(gy)

        _run(eng, [EffectSpec("seq", {"effects": [
            {"type": "shuffle_hand_and_graveyard_into_library",
             "params": {"scope": "each_player"}},
            {"type": "draw", "params": {"selector": "each_player", "count": 7}},
        ]})])

        assert len(p1.hand) == 7
        assert len(eng.state.player_by_id("p2").hand) == 7
        assert gy not in p1.graveyard  # shuffled into the library, not left behind

    def test_resource_aggregate_reduces_over_a_player_scope(self) -> None:
        from mtg_analyzer.game import effect_amounts

        eng = _engine()
        self._fill_hand(eng, "p1", 4)
        self._fill_hand(eng, "p2", 2)
        ctx = GameContext(eng.state, eng.rules)

        def measure(aggregate: str) -> int:
            return effect_amounts.amount_of(
                {"kind": "resource", "resource": "hand_size",
                 "aggregate": aggregate, "scope": "each_player"},
                ctx, None, None,
            )

        assert measure("max") == 4
        assert measure("min") == 2
        assert measure("sum") == 6

    def test_the_wheel_family_types_are_gone(self) -> None:
        for name in ("wheel", "wheel_of_fortune", "windfall"):
            assert not EffectRegistry.is_registered(name)
            assert name not in isa.EFFECT_TYPES

    def test_the_catalogue_entries_still_bind(self) -> None:
        from mtg_analyzer.game import ability_catalogue as ac

        for name in ("Timetwister", "Wheel of Fortune", "Windfall", "Day's Undoing"):
            card = Card(id=name, name=name, type_line="Sorcery", is_sorcery=True)
            specs = ac.specs_for(card)
            assert specs, name
            for spec in specs:
                build_effects(list(spec.effects), None)  # no BindError / KeyError


class TestB7ExileHandRetirement:
    """ENG-37 B7: `exile_hand_then_draw_that_many` (Invasion of Kaldheim)
    retired to a `bind` over ``resource: hand_size`` (the controller's,
    measured before the body) around a new `exile_hand` instruction and a
    `draw`. `exile_hand` is the hidden-zone sibling of `exile_library`.
    """

    def test_exile_the_whole_hand_then_draw_that_many(self) -> None:
        eng = _engine()
        p1 = eng.state.player_by_id("p1")
        for i in range(4):
            p1.hand.append(GameObject(
                Card(id=f"H{i}", name=f"H{i}", type_line="Land", is_land=True),
                owner_id="p1", zone=Zone.HAND,
            ))
        for i in range(10):
            p1.library.append(GameObject(
                Card(id=f"L{i}", name=f"L{i}", type_line="Creature", is_creature=True),
                owner_id="p1", zone=Zone.LIBRARY,
            ))
        src = _creature(eng.state, name="Siege", power=0, toughness=1)
        exiled_ids = {o.instance_id for o in p1.hand}
        lib_before = len(p1.library)

        _apply_effects_partitioned(
            build_effects([EffectSpec("bind", {
                "name": "n",
                "amount": {"kind": "resource", "resource": "hand_size"},
                "effects": [
                    {"type": "exile_hand", "params": {}},
                    {"type": "draw", "params": {"count": "$n"}},
                ],
            })], src),
            GameContext(eng.state, eng.rules), None, None, source=src,
        )

        assert len(p1.hand) == 4                     # drew back exactly what left
        assert lib_before - len(p1.library) == 4
        assert not p1.graveyard                      # exiled, not discarded
        assert exiled_ids.issubset({o.instance_id for o in p1.exile})

    def test_an_empty_hand_draws_nothing(self) -> None:
        eng = _engine()
        p1 = eng.state.player_by_id("p1")
        for i in range(5):
            p1.library.append(GameObject(
                Card(id=f"L{i}", name=f"L{i}", type_line="Creature", is_creature=True),
                owner_id="p1", zone=Zone.LIBRARY,
            ))
        src = _creature(eng.state, name="Siege", power=0, toughness=1)

        _apply_effects_partitioned(
            build_effects([EffectSpec("bind", {
                "name": "n",
                "amount": {"kind": "resource", "resource": "hand_size"},
                "effects": [
                    {"type": "exile_hand", "params": {}},
                    {"type": "draw", "params": {"count": "$n"}},
                ],
            })], src),
            GameContext(eng.state, eng.rules), None, None, source=src,
        )
        assert len(p1.hand) == 0
        assert len(p1.library) == 5

    def test_the_fused_type_is_gone(self) -> None:
        assert not EffectRegistry.is_registered("exile_hand_then_draw_that_many")
        assert "exile_hand_then_draw_that_many" not in isa.EFFECT_TYPES
        assert EffectRegistry.is_registered("exile_hand")

    def test_the_catalogue_entry_still_binds(self) -> None:
        from mtg_analyzer.game import ability_catalogue as ac

        card = Card(id="IoK", name="Invasion of Kaldheim",
                    type_line="Battle — Siege")
        specs = ac.specs_for(card)
        assert specs
        for spec in specs:
            build_effects(list(spec.effects), None)

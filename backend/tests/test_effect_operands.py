"""ENG-37 axis 4 — an effect operand naming a referent, and the first
fused types retired because of it.

`14_` §1.1's fourth axis: *who* an effect acts on. It was the last of the
three vocabularies missing, and it is what actually kept the 84 fused effect
types alive — not the composition axis, which ENG-37 built first and which
turned out not to be the blocker. A fusion existed because its second part
had to name what the first part produced ("destroy target permanent, **its
controller** gains 4 life"), and an operand could only be an already-resolved
player, never a referent. `ExileGainLifeToControllerEffect` said so in its own
docstring before it was deleted: "composing two effects here couldn't pass the
power along".

What this file pins:

* the operand vocabulary itself — defaults, scopes, referents, derivations,
  and the fail-safe direction;
* that it composes with the other two vocabularies, since a card needs all
  three at once (`bind` measures with `effect_amounts`, the recipient is named
  with this, the whole thing is gated by `effect_conditions`);
* the three retired fusions, each asserted as the *composition* rather than
  the class that used to exist.

Reference: mtg_analyzer/game/effect_operands.py,
mtg_analyzer/game/effect_amounts.py, mtg_analyzer/game/isa.py.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import effect_operands as ops
from mtg_analyzer.game import isa
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import EffectRegistry, GameContext, _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _permanent(state, owner="p1", name="Thing", type_line="Creature — Bear",
               power=2, toughness=2, mana_value=0):
    is_creature = "Creature" in type_line
    card = Card(
        id=name, name=name, type_line=type_line, is_creature=is_creature,
        # `Card` refuses power/toughness on a noncreature (RULE 208.1).
        power=power if is_creature else None,
        toughness=toughness if is_creature else None,
        converted_mana_cost=mana_value,
    )
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj


def _ctx(eng, previous=None):
    context = GameContext(eng.state, eng.rules)
    if previous:
        context.previous_targets = list(previous)
    return context


def _run(eng, specs, source=None, targets=None):
    return _apply_effects_partitioned(
        build_effects(specs, source), _ctx(eng), targets, None, source=source
    )


def _life(eng, player_id):
    return eng.state.player_by_id(player_id).life


class TestOperandVocabulary:
    def test_no_operand_means_the_ability_controller(self) -> None:
        # The default 174 effects hard-code as `_controller_of(self.source,
        # context)`; naming it explicitly must not change it.
        eng = _engine()
        source = _permanent(eng.state, "p2", "Src")
        players = ops.players_for(None, _ctx(eng), source)
        assert [p.id for p in players] == ["p2"]

    def test_an_already_resolved_player_passes_through(self) -> None:
        # Every existing caller passes one of these; the vocabulary is
        # additive, not a replacement.
        eng = _engine()
        bob = eng.state.player_by_id("p2")
        assert ops.players_for(bob, _ctx(eng)) == [bob]

    @pytest.mark.parametrize("scope,expected", [
        ("controller", ["p1"]),
        ("you", ["p1"]),
        ("each_player", ["p1", "p2"]),
        ("each_opponent", ["p2"]),
    ])
    def test_scopes_resolve_to_player_sets(self, scope: str, expected: list[str]) -> None:
        eng = _engine()
        source = _permanent(eng.state, "p1", "Src")
        assert [p.id for p in ops.players_for(scope, _ctx(eng), source)] == expected

    def test_a_referent_resolves_through_the_shared_axis(self) -> None:
        # "its controller" — the whole reason this module exists.
        eng = _engine()
        source = _permanent(eng.state, "p1", "Src")
        victim = _permanent(eng.state, "p2", "Victim")
        context = _ctx(eng, previous=[victim])
        players = ops.players_for(
            {"of": "previous_target", "as": "controller"}, context, source
        )
        assert [p.id for p in players] == ["p2"]

    def test_owner_and_controller_are_distinct_derivations(self) -> None:
        eng = _engine()
        source = _permanent(eng.state, "p1", "Src")
        stolen = _permanent(eng.state, "p2", "Stolen")
        stolen.controller_id = "p1"  # a control-change already resolved
        context = _ctx(eng, previous=[stolen])
        assert [p.id for p in ops.players_for(
            {"of": "previous_target", "as": "controller"}, context, source)] == ["p1"]
        assert [p.id for p in ops.players_for(
            {"of": "previous_target", "as": "owner"}, context, source)] == ["p2"]

    def test_a_referent_that_is_already_a_player_stays_itself(self) -> None:
        # "Its controller", asked of a player, is that player — a referent
        # that resolved to a player must not silently become nobody.
        eng = _engine()
        source = _permanent(eng.state, "p1", "Src")
        bob = eng.state.player_by_id("p2")
        context = _ctx(eng)
        players = ops.players_for(
            {"of": "target", "as": "controller"}, context, source, [bob]
        )
        assert [p.id for p in players] == ["p2"]

    def test_a_missing_referent_resolves_to_nobody(self) -> None:
        eng = _engine()
        source = _permanent(eng.state, "p1", "Src")
        assert ops.players_for(
            {"of": "previous_target", "as": "controller"}, _ctx(eng), source
        ) == []

    def test_an_unknown_scope_or_derivation_fails_safe(self) -> None:
        # Same direction as an unmodelled condition (never applies) and an
        # unmodelled amount (zero): the effect happens to no one.
        eng = _engine()
        source = _permanent(eng.state, "p1", "Src")
        victim = _permanent(eng.state, "p2", "Victim")
        context = _ctx(eng, previous=[victim])
        assert ops.players_for("no_such_scope", context, source) == []
        assert ops.players_for(
            {"of": "previous_target", "as": "no_such_derivation"}, context, source
        ) == []

    def test_player_for_takes_the_first_of_a_scope(self) -> None:
        eng = _engine()
        source = _permanent(eng.state, "p1", "Src")
        assert ops.player_for("each_player", _ctx(eng), source).id == "p1"
        assert ops.player_for("no_such_scope", _ctx(eng), source) is None


class TestOperandsReachRealEffects:
    def test_gain_life_pays_a_referent_recipient(self) -> None:
        eng = _engine()
        source = _permanent(eng.state, "p1", "Src")
        victim = _permanent(eng.state, "p2", "Victim")
        context = _ctx(eng, previous=[victim])
        effects = build_effects([EffectSpec("gain_life", {
            "amount": 3, "player": {"of": "previous_target", "as": "controller"},
        })], source)
        effects[0].apply(context, None)
        assert (_life(eng, "p1"), _life(eng, "p2")) == (20, 23)

    def test_lose_life_takes_one_too(self) -> None:
        eng = _engine()
        source = _permanent(eng.state, "p1", "Src")
        victim = _permanent(eng.state, "p2", "Victim")
        context = _ctx(eng, previous=[victim])
        effects = build_effects([EffectSpec("lose_life", {
            "amount": 3, "player": {"of": "previous_target", "as": "controller"},
        })], source)
        effects[0].apply(context, None)
        assert (_life(eng, "p1"), _life(eng, "p2")) == (20, 17)


class TestRetiredFusions:
    """Each of these was a registered effect type until ENG-37.

    Asserted as the composition the card now is, so the test fails if the
    replacement ever stops being expressible — which is the thing a deleted
    class can no longer protect.
    """

    @pytest.mark.parametrize("retired", [
        "exile_gain_life_equal_power",
        "destroy_gain_life_to_controller",
        "destroy_lose_life_equal_mana_value",
    ])
    def test_the_fused_type_is_gone(self, retired: str) -> None:
        assert not EffectRegistry.is_registered(retired)
        assert retired not in isa.EFFECT_TYPES

    def test_swords_to_plowshares(self) -> None:
        # "Exile target creature. Its controller gains life equal to its
        # power." Both halves need a referent: the amount and the recipient.
        eng = _engine()
        source = _permanent(eng.state, "p1", "Src")
        titan = _permanent(eng.state, "p2", "Titan", power=6, toughness=6)
        _run(eng, [
            EffectSpec("exile", {"target_kind": "creature"}),
            EffectSpec("bind", {
                "name": "power",
                "amount": {"kind": "characteristic", "characteristic": "power",
                           "of": "previous_target"},
                "effects": [{"type": "gain_life", "params": {
                    "amount": "$power",
                    "player": {"of": "previous_target", "as": "controller"},
                }}],
            }),
        ], source=source, targets=[titan])
        assert titan not in eng.state.battlefield
        assert (_life(eng, "p1"), _life(eng, "p2")) == (20, 26)

    def test_natures_claim(self) -> None:
        # "Destroy target artifact or enchantment. Its controller gains 4
        # life." — a referent recipient with a *printed* amount, so no bind.
        eng = _engine()
        source = _permanent(eng.state, "p1", "Src")
        relic = _permanent(eng.state, "p2", "Relic", type_line="Artifact")
        _run(eng, [
            EffectSpec("destroy", {"target_kind": "permanent"}),
            EffectSpec("gain_life", {
                "amount": 4, "player": {"of": "previous_target", "as": "controller"},
            }),
        ], source=source, targets=[relic])
        assert relic not in eng.state.battlefield
        assert (_life(eng, "p1"), _life(eng, "p2")) == (20, 24)

    def test_feed_the_swarm(self) -> None:
        # "Destroy target creature or enchantment. You lose life equal to its
        # mana value." — the mirror case: a measured amount, but the printed
        # recipient is "you", so only `bind` is needed.
        eng = _engine()
        source = _permanent(eng.state, "p1", "Src")
        relic = _permanent(eng.state, "p2", "Relic", type_line="Enchantment",
                           mana_value=4)
        _run(eng, [
            EffectSpec("destroy", {"target_kind": "permanent"}),
            EffectSpec("bind", {
                "name": "mv",
                "amount": {"kind": "characteristic", "characteristic": "mana_value",
                           "of": "previous_target"},
                "effects": [{"type": "lose_life", "params": {"amount": "$mv"}}],
            }),
        ], source=source, targets=[relic])
        assert relic not in eng.state.battlefield
        assert (_life(eng, "p1"), _life(eng, "p2")) == (16, 20)

    def test_mana_value_reads_the_printed_card(self) -> None:
        # A regression pin: `Card` spells this `converted_mana_cost`, and
        # because an unreadable measurement is 0 by design, getting the field
        # name wrong made Feed the Swarm lose *no* life, silently.
        from mtg_analyzer.game import effect_amounts

        eng = _engine()
        source = _permanent(eng.state, "p1", "Src")
        relic = _permanent(eng.state, "p2", "Relic", type_line="Artifact",
                           mana_value=5)
        measured = effect_amounts.amount_of(
            {"kind": "characteristic", "characteristic": "mana_value",
             "of": "previous_target"},
            _ctx(eng, previous=[relic]), source,
        )
        assert measured == 5

"""Tests for the effect binder + the Phase 0 end-to-end seam.

Reference: docs/09_ORACLE_EFFECT_PARSER.md ("RUNTIME LINKING", the two-stage
compiler). Phase 0 proves IR -> binder -> engine with a hand-authored spec
and NO parsing: a Lightning Bolt whose `AbilitySpec` is written by hand
resolves as real damage through the existing rules engine.
"""

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.mana_cost import ManaCost
from mtg_analyzer.models.player import Player
from mtg_analyzer.game.effects import ActivatedAbility, DealDamageEffect, TriggeredAbility
from mtg_analyzer.game.effect_binder import BindError, attach_to_object, bind_ability, build_effects
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec


class TestBuildEffects:
    def test_builds_a_registered_effect(self):
        [effect] = build_effects([EffectSpec("damage", {"amount": 3})])
        assert isinstance(effect, DealDamageEffect)
        assert effect.amount == 3

    def test_unknown_effect_type_is_refused(self):
        with pytest.raises(BindError, match="no registered effect"):
            build_effects([EffectSpec("summon_ancient_one", {})])

    def test_source_is_threaded_onto_the_effect(self):
        sentinel = object()
        [effect] = build_effects([EffectSpec("draw", {"count": 1})], source=sentinel)
        assert effect.source is sentinel


class TestBindAbility:
    def test_spell_effect_returns_effect_list(self):
        spec = AbilitySpec("spell_effect", [EffectSpec("damage", {"amount": 3})])
        bound = bind_ability(spec)
        assert isinstance(bound, list) and isinstance(bound[0], DealDamageEffect)

    def test_triggered_returns_triggered_ability(self):
        spec = AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={"event": "ENTERS_BATTLEFIELD"},
        )
        bound = bind_ability(spec)
        assert isinstance(bound, TriggeredAbility)
        assert bound.trigger_event == "ENTERS_BATTLEFIELD"

    def test_activated_returns_activated_ability(self):
        spec = AbilitySpec(
            "activated", [EffectSpec("draw", {"count": 1})], cost={"taps_self": True}
        )
        bound = bind_ability(spec)
        assert isinstance(bound, ActivatedAbility)
        assert bound.taps_source is True

    def test_unsupported_kind_is_refused(self):
        with pytest.raises(BindError, match="does not support"):
            bind_ability(AbilitySpec("static", [EffectSpec("draw", {"count": 1})]))


class TestAttachToObject:
    def test_spell_effect_populates_spell_effects_hook(self):
        card = Card(id="bolt", name="Lightning Bolt", type_line="Instant", is_instant=True)
        obj = GameObject(card, owner_id="p1")
        attach_to_object(obj, [AbilitySpec("spell_effect", [EffectSpec("damage", {"amount": 3})])])
        assert len(obj.spell_effects) == 1
        assert isinstance(obj.spell_effects[0], DealDamageEffect)

    def test_triggered_populates_triggered_abilities(self):
        card = Card(id="c", name="Wall of Omens", type_line="Creature — Wall", is_creature=True,
                    power=0, toughness=4)
        obj = GameObject(card, owner_id="p1")
        attach_to_object(
            obj,
            [AbilitySpec("triggered", [EffectSpec("draw", {"count": 1})],
                         trigger={"event": "ENTERS_BATTLEFIELD"})],
        )
        assert len(obj.triggered_abilities) == 1


class TestLightningBoltEndToEnd:
    """The Phase 0 milestone: a hand-authored spec resolves as real damage."""

    def test_bolt_deals_three_to_a_player(self):
        bolt_card = Card(
            id="bolt",
            name="Lightning Bolt",
            type_line="Instant",
            mana_cost_string="{R}",
            converted_mana_cost=ManaCost.parse("{R}").converted_mana_cost,
            is_instant=True,
            oracle_text="Lightning Bolt deals 3 damage to any target.",
        )
        caster = Player(id="p1", life=20)
        opponent = Player(id="p2", life=20)
        bolt = GameObject(bolt_card, owner_id="p1", zone=Zone.HAND)
        caster.hand.append(bolt)

        # Hand-authored IR (no parser yet) -> binder -> spell_effects hook.
        attach_to_object(
            bolt,
            [AbilitySpec(
                ability_kind="spell_effect",
                effects=[EffectSpec("damage", {"amount": 3})],
                target={"kind": "any"},
                raw_text=bolt_card.oracle_text,
            )],
        )

        state = GameState(players=[caster, opponent])
        engine = RulesEngine(state)
        caster.mana_pool.add("R", 1)

        engine.cast_spell(caster, bolt, targets=[opponent])
        engine.resolve_top_of_stack()

        assert opponent.life == 17  # 20 - 3, dealt through the real engine
        assert bolt.zone == Zone.GRAVEYARD  # instant resolved to graveyard

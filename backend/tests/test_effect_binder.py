"""Tests for the effect binder + the Phase 0 end-to-end seam.

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md ("RUNTIME LINKING", the two-stage
compiler). Phase 0 proves IR -> binder -> engine with a hand-authored spec
and NO parsing: a Lightning Bolt whose `AbilitySpec` is written by hand
resolves as real damage through the existing rules engine.
"""

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.mana_cost import ManaCost
from mtg_analyzer.models.player import Player
from mtg_analyzer.game.effects import (
    ActivatedAbility,
    DealDamageEffect,
    ReplacementEffect,
    StaticAbility,
    TriggeredAbility,
)
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


class TestStaticEffectRegistryBridges:
    """`EffectSpec` -> `StaticAbility` for the layers continuous.py implements
    but that (before this) had no whitelisted way to be authored: layer 2
    (control), layer 5 (colour), layer 7a (CDA) and layer 7e (switch)."""

    def test_color_change_defaults_to_attached_permanent(self):
        [effect] = build_effects([EffectSpec("color_change", {"colors": ["b"]})])
        assert isinstance(effect, StaticAbility)
        assert effect.layer == "color"
        assert effect.affects == "attached_permanent"
        assert effect.params == {"colors": ["B"], "set": True}

    def test_control_change_defaults_to_attached_permanent(self):
        [effect] = build_effects([EffectSpec("control_change", {})])
        assert effect.layer == "control"
        assert effect.affects == "attached_permanent"
        assert effect.params == {"controller": None}

    def test_pt_cda_carries_its_count_selectors(self):
        [effect] = build_effects(
            [EffectSpec("pt_cda", {"power_count": "creatures_you_control",
                                    "toughness_count": "creatures_you_control"})]
        )
        assert effect.layer == "pt_cda"
        assert effect.affects == "self"
        assert effect.params["power_count"] == "creatures_you_control"

    def test_pt_switch_defaults_to_self(self):
        [effect] = build_effects([EffectSpec("pt_switch", {})])
        assert effect.layer == "pt_switch"
        assert effect.affects == "self"


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
        # "keyword" specs are bound by attach_keyword, not bind_ability.
        with pytest.raises(BindError, match="does not support"):
            bind_ability(AbilitySpec("keyword", keyword={"name": "flying"}))

    def test_replacement_returns_replacement_effect_list(self):
        spec = AbilitySpec(
            "replacement", [EffectSpec("prevent_damage", {"amount": "all", "to": "self"})]
        )
        bound = bind_ability(spec)
        assert isinstance(bound, list) and isinstance(bound[0], ReplacementEffect)
        assert bound[0].event_type == EventType.DAMAGE

    def test_replacement_refuses_an_unregistered_family(self):
        spec = AbilitySpec("replacement", [EffectSpec("draw", {"count": 1})])
        with pytest.raises(BindError, match="no registered replacement"):
            bind_ability(spec)


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

    def test_replacement_populates_replacement_effects(self):
        card = Card(id="shield", name="Shielded Wall", type_line="Creature — Wall",
                    is_creature=True, power=0, toughness=4)
        obj = GameObject(card, owner_id="p1")
        attach_to_object(
            obj,
            [AbilitySpec(
                "replacement",
                [EffectSpec("prevent_damage", {"amount": "all", "to": "self"})],
            )],
        )
        assert len(obj.replacement_effects) == 1
        assert isinstance(obj.replacement_effects[0], ReplacementEffect)


class TestPreventDamageEndToEnd:
    """A bound `prevent_damage` replacement actually stops damage (RULE 615)."""

    def test_prevent_all_damage_to_self(self):
        state = GameState([Player(id="p1", life=20)])
        wall_card = Card(id="wall", name="Fog Wall", type_line="Creature — Wall",
                          is_creature=True, power=0, toughness=4)
        wall = GameObject(wall_card, owner_id="p1", zone=Zone.BATTLEFIELD)
        attach_to_object(
            wall,
            [AbilitySpec(
                "replacement",
                [EffectSpec("prevent_damage", {"amount": "all", "to": "self"})],
            )],
        )
        state.add_to_battlefield(wall)
        rules = RulesEngine(state)
        rules.deal_damage(wall, 5, source=None)
        assert wall.damage_marked == 0

    def test_prevent_partial_damage_to_self(self):
        state = GameState([Player(id="p1", life=20)])
        wall_card = Card(id="wall", name="Partial Shield", type_line="Creature — Wall",
                          is_creature=True, power=0, toughness=10)
        wall = GameObject(wall_card, owner_id="p1", zone=Zone.BATTLEFIELD)
        attach_to_object(
            wall,
            [AbilitySpec(
                "replacement",
                [EffectSpec("prevent_damage", {"amount": 2, "to": "self"})],
            )],
        )
        state.add_to_battlefield(wall)
        rules = RulesEngine(state)
        rules.deal_damage(wall, 5, source=None)
        assert wall.damage_marked == 3  # 5 - 2 prevented


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

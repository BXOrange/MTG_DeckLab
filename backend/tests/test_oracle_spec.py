"""Tests for the AbilitySpec IR + its validation (parser front-end).

Reference: docs/09_ORACLE_EFFECT_PARSER.md ("THE INTERMEDIATE
REPRESENTATION", "SECURITY MODEL": clamp params).
"""

import pytest

from mtg_analyzer.parser.oracle.spec import (
    MAX_EFFECT_MAGNITUDE,
    AbilitySpec,
    EffectSpec,
    ParserProvenance,
    SpecValidationError,
)


class TestValidate:
    def test_valid_spell_effect_passes(self):
        spec = AbilitySpec(
            ability_kind="spell_effect",
            effects=[EffectSpec("damage", {"amount": 3})],
            target={"kind": "any"},
            raw_text="deal 3 damage to any target",
        )
        assert spec.validate() is spec

    def test_unknown_ability_kind_is_rejected(self):
        with pytest.raises(SpecValidationError, match="unknown ability_kind"):
            AbilitySpec(ability_kind="wish").validate()

    def test_effect_bearing_kind_requires_an_effect(self):
        with pytest.raises(SpecValidationError, match="at least one effect"):
            AbilitySpec(ability_kind="spell_effect", effects=[]).validate()

    def test_triggered_needs_an_event(self):
        spec = AbilitySpec(
            ability_kind="triggered", effects=[EffectSpec("draw", {"count": 1})]
        )
        with pytest.raises(SpecValidationError, match="trigger"):
            spec.validate()

    def test_triggered_with_event_passes(self):
        spec = AbilitySpec(
            ability_kind="triggered",
            effects=[EffectSpec("draw", {"count": 1})],
            trigger={"event": "ENTERS_BATTLEFIELD"},
        )
        assert spec.validate() is spec

    def test_keyword_kind_needs_no_effects(self):
        assert AbilitySpec(ability_kind="keyword", raw_text="Flying").validate()


class TestParamClamping:
    def test_absurd_magnitude_is_clamped(self):
        spec = AbilitySpec(
            ability_kind="spell_effect", effects=[EffectSpec("draw", {"count": 10**9})]
        ).validate()
        assert spec.effects[0].params["count"] == MAX_EFFECT_MAGNITUDE

    def test_negative_is_clamped_to_zero(self):
        spec = AbilitySpec(
            ability_kind="spell_effect", effects=[EffectSpec("damage", {"amount": -5})]
        ).validate()
        assert spec.effects[0].params["amount"] == 0

    def test_normal_values_are_untouched(self):
        spec = AbilitySpec(
            ability_kind="spell_effect", effects=[EffectSpec("damage", {"amount": 3})]
        ).validate()
        assert spec.effects[0].params["amount"] == 3


class TestSerialization:
    def test_round_trip(self):
        spec = AbilitySpec(
            ability_kind="triggered",
            effects=[EffectSpec("draw", {"count": 1})],
            trigger={"event": "ENTERS_BATTLEFIELD"},
            target={"kind": "self"},
            optional=True,
            raw_text="When this enters, you may draw a card.",
            parser=ParserProvenance(version="1", source="rule:etb-draw", confidence=0.9),
        )
        restored = AbilitySpec.from_dict(spec.to_dict())
        assert restored.to_dict() == spec.to_dict()
        assert restored.parser.source == "rule:etb-draw"

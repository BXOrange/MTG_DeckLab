"""ENG-37 — `AbilitySpec.validate()` reaches every nesting depth.

`validate()` walked only `self.effects`, so docs/09's two security-model
guarantees — *clamp numeric params*, *whitelist conditions* — held at depth 0
and nowhere else. The engine has carried nested spec lists for a long time
(`pay_cost_then`'s `on_pay_effect_specs`, `repeat_process`'s `effects`,
`create_delayed_trigger`, `choose_objects`' `then_specs`, a modal option's
own list), and a "draw 10^9 cards" parked one level down inside one of those
wedged a session exactly as well as at depth 0.

These tests pin the fix at the boundary rather than through the engine: the
spec layer *is* the security boundary (docs/09), so it has to be provably
total on its own.
"""
from __future__ import annotations

import pytest

from mtg_analyzer.parser.oracle.spec import (
    MAX_EFFECT_MAGNITUDE,
    AbilitySpec,
    EffectSpec,
    SpecValidationError,
)


def _spell(*effects: EffectSpec) -> AbilitySpec:
    return AbilitySpec("spell_effect", effects=list(effects))


class TestNestedClamping:
    def test_depth_zero_still_clamps(self) -> None:
        spec = _spell(EffectSpec("draw", {"count": 10 ** 9})).validate()
        assert spec.effects[0].params["count"] == MAX_EFFECT_MAGNITUDE

    def test_a_nested_spec_list_is_clamped(self) -> None:
        # The `pay_cost_then` shape: "you may pay {2}. If you do, draw N."
        spec = _spell(EffectSpec("pay_cost_then", {
            "on_pay_effect_specs": [
                {"type": "draw", "params": {"count": 10 ** 9}},
            ],
        })).validate()
        nested = spec.effects[0].params["on_pay_effect_specs"][0]
        assert nested["params"]["count"] == MAX_EFFECT_MAGNITUDE

    def test_clamping_reaches_two_levels_down(self) -> None:
        spec = _spell(EffectSpec("repeat_process", {
            "effects": [
                {"type": "pay_cost_then", "params": {
                    "then_specs": [
                        {"type": "damage", "params": {"amount": 10 ** 9}},
                    ],
                }},
            ],
        })).validate()
        inner = (spec.effects[0].params["effects"][0]
                 ["params"]["then_specs"][0]["params"])
        assert inner["amount"] == MAX_EFFECT_MAGNITUDE

    def test_a_nested_effect_spec_object_is_clamped(self) -> None:
        # Modal options carry `EffectSpec` objects rather than dicts, so both
        # forms have to be recognised.
        spec = _spell(EffectSpec("choose_objects", {
            "then_specs": [EffectSpec("mill", {"count": 10 ** 9})],
        })).validate()
        assert spec.effects[0].params["then_specs"][0].params["count"] == (
            MAX_EFFECT_MAGNITUDE
        )

    def test_recognition_is_structural_not_name_keyed(self) -> None:
        # Nested lists are spelled a dozen different ways across the effect
        # factories; a name-keyed walk would miss the next one. An invented
        # param name must still be clamped.
        spec = _spell(EffectSpec("some_future_effect", {
            "a_brand_new_param_name": [
                {"type": "draw", "params": {"count": 10 ** 9}},
            ],
        })).validate()
        assert spec.effects[0].params["a_brand_new_param_name"][0][
            "params"]["count"] == MAX_EFFECT_MAGNITUDE


class TestNestedConditionWhitelist:
    def test_a_nested_unknown_condition_key_is_rejected(self) -> None:
        with pytest.raises(SpecValidationError, match="unknown effect condition key"):
            _spell(EffectSpec("pay_cost_then", {
                "then_specs": [
                    {"type": "draw", "params": {},
                     "condition": {"arbitrary_evil_key": True}},
                ],
            })).validate()

    def test_a_nested_known_condition_key_is_accepted(self) -> None:
        spec = _spell(EffectSpec("pay_cost_then", {
            "then_specs": [
                {"type": "draw", "params": {}, "condition": {"kicked": True}},
            ],
        })).validate()
        assert spec.effects[0].params["then_specs"][0]["condition"] == {"kicked": True}


class TestWhitelistMatchesEvaluator:
    """The whitelist and the evaluator must name the same keys.

    Recursing into nested specs immediately caught a real drift: Frodo,
    Sauron's Bane shipped `ring_tempted_at_most`, which
    `ConditionalEffect._condition_holds` evaluates but
    `_ALLOWED_CONDITION_KEYS` did not list. It survived because the card
    nests it — the same key at depth 0 would have been rejected all along.
    A whitelist that disagrees with its evaluator is either a dead key or an
    ungated one, and both are worth failing on.
    """

    @staticmethod
    def _evaluated_keys() -> set[str]:
        import re

        from mtg_analyzer.game.effects import core

        source = inspect_source(core, "_condition_holds")
        return set(re.findall(r'self\.condition\.get\(\s*"([a-z_]+)"', source))

    def test_every_evaluated_key_is_whitelisted(self) -> None:
        from mtg_analyzer.parser.oracle.spec import _ALLOWED_CONDITION_KEYS

        ungated = sorted(self._evaluated_keys() - _ALLOWED_CONDITION_KEYS)
        assert not ungated, (
            f"`_condition_holds` evaluates {ungated}, which "
            f"`_ALLOWED_CONDITION_KEYS` does not list — a card-text-derived "
            f"value reaching the engine through an ungated key is exactly "
            f"what docs/09's security model forbids."
        )

    def test_every_whitelisted_key_is_evaluated(self) -> None:
        from mtg_analyzer.parser.oracle.spec import _ALLOWED_CONDITION_KEYS

        dead = sorted(_ALLOWED_CONDITION_KEYS - self._evaluated_keys())
        assert not dead, (
            f"`_ALLOWED_CONDITION_KEYS` lists {dead}, which nothing "
            f"evaluates — a condition that silently never holds."
        )


def inspect_source(module, function_name: str) -> str:
    """The source of one method of `ConditionalEffect`, by name."""
    import inspect

    source = inspect.getsource(module)
    start = source.index(f"def {function_name}")
    end = source.index("\n    def ", start + 1)
    return source[start:end]


class TestDepthCap:
    def test_absurd_nesting_fails_closed(self) -> None:
        # The cap exists so validation itself cannot become the denial of
        # service — same reasoning as MAX_EFFECT_MAGNITUDE.
        node: dict = {"type": "draw", "params": {"count": 1}}
        for _ in range(AbilitySpec.MAX_SPEC_DEPTH + 4):
            node = {"type": "pay_cost_then", "params": {"then_specs": [node]}}
        with pytest.raises(SpecValidationError, match="nests deeper than"):
            _spell(EffectSpec(node["type"], node["params"])).validate()

    def test_realistic_nesting_still_validates(self) -> None:
        # The deepest shipped shapes are around three levels; the cap must
        # not be tight enough to reject a real card.
        spec = _spell(EffectSpec("pay_cost_then", {
            "then_specs": [
                {"type": "choose_objects", "params": {
                    "then_specs": [
                        {"type": "pay_cost_then", "params": {
                            "then_specs": [
                                {"type": "draw", "params": {"count": 2}},
                            ],
                        }},
                    ],
                }},
            ],
        })).validate()
        assert spec is not None

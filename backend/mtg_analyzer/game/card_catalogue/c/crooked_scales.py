"""Crooked Scales."""
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _crooked_scales():
    """{4}, {T}: Flip a coin. If you win the flip, destroy target creature an opponent controls. If you lose the flip, destroy target creature you control unless you pay {3} and repeat this process."""
    return [AbilitySpec(
        "activated", [EffectSpec("coin_flip_destroy_or_pay_repeat", {})],
        cost={"mana": "{4}", "taps_self": True},
    )]


register("Crooked Scales", _crooked_scales)

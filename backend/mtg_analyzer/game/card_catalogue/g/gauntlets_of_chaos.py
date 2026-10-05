from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _gauntlets_of_chaos() -> list[AbilitySpec]:
    """{5}, Sacrifice this artifact: Exchange control of target artifact,
    creature, or land you control and target permanent an opponent
    controls that shares one of those types with it. If those permanents
    are exchanged this way, destroy all Auras attached to them.

    — The two-explicit-targets mode plus both new `ExchangeControlEffect`
    riders: `shares_type="card"` (the cross-target predicate) and
    `destroy_auras_if_exchanged` (RULE 701.10c's own after-effect, gated on
    the exchange actually happening).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("exchange_control", {
                "first_target_kind": "permanent_you_control",
                "target_kind": "permanent_you_dont_control",
                "shares_type": "card",
                "destroy_auras_if_exchanged": True,
            })],
            cost={"text": "{5}, Sacrifice ~"},
        ),
    ]


register("Gauntlets of Chaos", _gauntlets_of_chaos)

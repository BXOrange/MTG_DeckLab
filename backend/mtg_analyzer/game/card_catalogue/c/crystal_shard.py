from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _crystal_shard() -> list[AbilitySpec]:
    """{3}, {T} or {U}, {T}: Return target creature to its owner's hand unless
    its controller pays {1}.

    — PLAY-ALL Step 2 (Wick Snail Boom). The "or" between the two costs is two
    separate activated abilities with the same body. The body is
    `pay_cost_then` over a ``creature`` target — the target's controller is
    the payer (``payer: target_controller``), and "unless they pay" is its
    ``else_effects`` branch, a `return_to_hand` that is handed that same target
    (the branch effects are built when the choice is answered and receive the
    original targets, `PayCostThenEffect.apply`). Its ``target_kind`` must name
    the creature kind — ``None`` would mean "the source" and bounce the Shard.
    """
    def bounce_unless_pays_one() -> EffectSpec:
        return EffectSpec("pay_cost_then", {
            "cost": "{1}", "payer": "target_controller", "target_kind": "creature",
            "else_effects": [{"type": "return_to_hand", "params": {"target_kind": "creature"}}],
        })

    return [
        AbilitySpec("activated", [bounce_unless_pays_one()], cost={"text": "{3}, {T}"}),
        AbilitySpec("activated", [bounce_unless_pays_one()], cost={"text": "{U}, {T}"}),
    ]


register("Crystal Shard", _crystal_shard)

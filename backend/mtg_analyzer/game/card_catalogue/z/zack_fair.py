from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _zack_fair() -> list[AbilitySpec]:
    """Zack Fair enters with a +1/+1 counter on it.
    {1}, Sacrifice Zack Fair: Target creature you control gains indestructible until end of turn. Put Zack Fair's counters on that creature and attach an Equipment that was attached to Zack Fair to that creature.

    — PLAY-ALL (Limit Break). The entry counter is oracle-derived. The ability is `transfer_sacrificed_legacy` after the sacrifice cost: the cost now stamps the
    sacrificed permanent's last-known counters and attached Equipment (`GameObject.sacrificed_cost_counters`/`sacrificed_cost_attached_ids`, RULE 608.2h), since
    the Equipment unattaches and the counters leave with Zack as soon as he is sacrificed.
    """
    return [
        AbilitySpec("activated", [EffectSpec("transfer_sacrificed_legacy", {})], cost={"text": "{1}, Sacrifice ~"}),
    ]


register("Zack Fair", _zack_fair)

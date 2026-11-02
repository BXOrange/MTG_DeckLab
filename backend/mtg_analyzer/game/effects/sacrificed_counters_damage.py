"""Damage equal to the counters the sacrificed source carried.

"{4}, Sacrifice this artifact: It deals damage equal to the number of charge counters on it to target player and
that much damage to up to one target creature." (Dragonspark Reactor.) The cost stamps the source's last-known
counters (`GameObject.sacrificed_cost_counters`, RULE 608.2h) because the permanent is already in the graveyard,
and a new object without counters, by the time the ability resolves.
"""
from __future__ import annotations

from ..targeting import TargetSpec
from .core import EffectRegistry, GameEffect


class SacrificedCountersDamageEffect(GameEffect):
    """RULE 120.3/608.2h: that many damage to the player target and, separately, to the optional creature target."""

    def __init__(self, kind: str = "charge", source=None) -> None:
        super().__init__(source)
        self.kind = kind
        self.target_spec = TargetSpec(kind="player")
        self.extra_target_specs = (TargetSpec(kind="creature", optional=True),)

    def apply(self, context, targets=None):
        amount = int((getattr(self.source, "sacrificed_cost_counters", None) or {}).get(self.kind, 0))
        if amount <= 0:
            return
        # Both hits come from the same source; each target is dealt "that much", independently (RULE 120.3).
        for target in [t for t in (targets or []) if t is not None]:
            context.deal_damage(target, amount, self.source)
        context.recompute()


EffectRegistry.register("sacrificed_counters_damage", lambda p: SacrificedCountersDamageEffect(str(p.get("kind", "charge"))))

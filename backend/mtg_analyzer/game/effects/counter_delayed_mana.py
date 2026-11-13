"""A counterspell's paid-mana quantity survives its target's zone change."""
from __future__ import annotations

from .core import EffectRegistry
from .stack import CounterSpellEffect


class CounterThenDelayedSpentManaEffect(CounterSpellEffect):
    def apply(self, context, targets=None):
        from .choices_actions import CreateDelayedTriggerEffect
        from ..effect_conditions import condition_holds

        if not targets:
            return
        spell = getattr(targets[0], "obj", None) or targets[0]
        # RULE 400.7: zone changes reset casting metadata; remember it first.
        spent = int(getattr(spell, "mana_spent_to_cast", 0) or 0)
        super().apply(context, targets)
        if condition_holds({"kind": "controls_subtype", "subtype": "Wizard"},
                           context, self.source, targets):
            CreateDelayedTriggerEffect(
                step="main", scope="controller", source=self.source,
                effects=[{"type": "add_mana", "params": {"color": "C", "amount": spent}}],
                description="Mana Sculpt: add the mana spent to cast the countered spell",
            ).apply(context)


EffectRegistry.register("counter_then_delayed_spent_mana", lambda p: CounterThenDelayedSpentManaEffect())

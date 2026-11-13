"""Announced divided damage followed by simultaneous damage back."""
from __future__ import annotations

import copy

from .core import EffectRegistry
from .damage_draw import DealDamageEffect
from .. import continuations


class DividedRetaliationEffect(DealDamageEffect):
    announce_trigger_division = True

    def __init__(self):
        super().__init__(amount=0, target_kind="creature_including_self", optional=True, divided=True)
        self.announced_total = None

    @property
    def target_specs(self):
        from ..targeting import TargetSpec

        count = self.announced_total
        if count is None:
            count = max(0, int(getattr(self.source, "power", 0) or 0))
        return [TargetSpec(kind="creature_including_self", optional=True, count=count)]

    def announced_copy(self, state=None, event=None):
        frozen = copy.copy(self)
        visit = (event or {}).get("source_zone_incarnation", getattr(self.source, "zone_incarnation", None))
        source = self.source
        if state is not None and source is not None and source.zone_incarnation != visit:
            source = state.zone_visit_sources.get((source.instance_id, visit), source)
        frozen.announced_total = max(0, int(getattr(source, "power", 0) or 0))
        frozen.source_visit = visit
        frozen.amount = frozen.announced_total
        frozen.division = None
        return frozen

    def apply(self, context, targets=None):
        from ...models.game.game_object import Zone

        picks = list(targets or [])
        if self.division is None:
            return
        # RULE 608.2b: None slots keep illegal targets' original shares.
        dealer = self.source
        source_visit = getattr(self, "source_visit", context.resolving_source_incarnation)
        if dealer is not None and dealer.zone_incarnation != source_visit:
            dealer = context.state.zone_visit_sources.get((dealer.instance_id, source_visit), dealer)
        with context.state.simultaneous():
            for target, amount in zip(picks, self.division):
                if target is not None:
                    context.deal_damage(target, amount, dealer)
        if (self.source is None or self.source.zone != Zone.BATTLEFIELD
                or (source_visit is not None and self.source.zone_incarnation != source_visit)):
            return
        # RULE 120.4: measure all retaliators before the simultaneous damage
        # instruction, and before state-based actions destroy lethal creatures.
        back = [(target, max(0, int(target.power or 0))) for target in picks if target is not None]
        with context.state.simultaneous():
            for target, amount in back:
                context.deal_damage(self.source, amount, target)


def begin_division(rules, item):
    effects = [effect for effect in item.effects if isinstance(effect, DividedRetaliationEffect)]
    if not effects:
        return
    effect = effects[0]
    targets = item.targets or []
    if len(targets) < 2:
        effect.division = [effect.announced_total] if targets else []
        return
    _ask(rules, item, effect, [], effect.announced_total)


def _ask(rules, item, effect, shares, remaining):
    target = item.targets[len(shares)]
    maximum = remaining - (len(item.targets) - len(shares) - 1)
    rules.open_choice({
        "kind": "trigger_damage_division", "player_id": item.controller_id,
        "stack_id": item.stack_id, "shares": shares, "remaining": remaining,
        "prompt": f"Schaden für {target.name} wählen", "allow_decline": False,
        "options": [{"id": str(amount), "label": str(amount)} for amount in range(1, maximum + 1)],
    })


@continuations.choice("trigger_damage_division", answer=continuations.ANSWER_INT_REQUIRED, rule="603.3d")
def _resume_division(rules, choice, amount):
    item = next((item for item in rules.state.stack if item.stack_id == choice["stack_id"]), None)
    if item is None:
        raise ValueError("the trigger is no longer on the stack")
    if str(amount) not in {option["id"] for option in choice["options"]}:
        raise ValueError("invalid damage share")
    effect = next(effect for effect in item.effects if isinstance(effect, DividedRetaliationEffect))
    shares = [*choice["shares"], amount]
    remaining = choice["remaining"] - amount
    if len(shares) == len(item.targets) - 1:
        effect.division = [*shares, remaining]
        queue = rules._pending_trigger_queue
        rules._pending_trigger_queue = []
        rules._place_triggers(queue)
    else:
        _ask(rules, item, effect, shares, remaining)


EffectRegistry.register("divided_damage_then_retaliate", lambda p: DividedRetaliationEffect())

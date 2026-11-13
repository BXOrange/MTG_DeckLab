"""The next combat-damage occurrence to players becomes a batch of tokens."""
from .core import GameEffect, ReplacementEffect, _controller_of
from ..durations import stamp
from ..targeting import TargetSpec
from ...models.game.events import EventType


class CombatPreventionTokensEffect(GameEffect):
    def __init__(self, source=None):
        super().__init__(source)
        self.target_spec = TargetSpec(kind="creature")

    def apply(self, context, targets=None):
        creature = targets[0] if targets else None
        player = _controller_of(self.source, context)
        if creature is None or player is None:
            return
        shield = _CombatTokenShield(creature, player.id, self.source)
        stamp(shield, context, self.source, "end_of_combat", affected=creature)
        player.player_effects.append(shield)


class _CombatTokenShield(ReplacementEffect):
    def __init__(self, creature, controller_id, source):
        super().__init__(EventType.DAMAGE, self._prevent, self._matches, source=source)
        self.watched_id = creature.instance_id
        self.watched_visit = creature.zone_incarnation
        self.controller_id = controller_id
        self.used_batch = None
        self.pending_amount = 0
        self.prevents_damage = True

    def _matches(self, event, context):
        return (event.get("source_id") == self.watched_id
                and event.get("source_zone_incarnation") == self.watched_visit
                and event.get("combat") and event.get("is_player")
                and event.get("amount", 0) > 0
                and (self.used_batch is None or self.used_batch == event.get("damage_batch_id")))

    def _prevent(self, event, context):
        # RULE 510.2: all player recipients in this damage step are one occurrence.
        self.used_batch = event.get("damage_batch_id")
        self.pending_amount += int(event.get("amount", 0))
        batch = context.state.combat_damage_batch
        if batch is None:
            self.settle_prevention(context)
        else:
            payoffs = batch.setdefault("prevention_payoffs", [])
            if self not in payoffs:
                payoffs.append(self)
        return None

    def settle_prevention(self, context):
        from ..binding.core import build_effects
        from ...parser.oracle.spec import EffectSpec

        amount, self.pending_amount = self.pending_amount, 0
        if not amount:
            return
        effect = build_effects([EffectSpec("create_token", {
            "token_name": "Phyrexian Mite", "count": amount,
            "power": 1, "toughness": 1, "colors": [], "subtypes": ["Phyrexian", "Mite"],
            "is_artifact": True, "parametric_keywords": [{"name": "toxic", "n": 1}],
            "keywords": ["cant_block"], "oracle_text": "Toxic 1\nThis token can't block.",
        })], self.source)[0]
        prior = context.acting_player_id
        context.acting_player_id = self.controller_id
        try:
            with context.state.simultaneous():
                effect.apply(context)
        finally:
            context.acting_player_id = prior

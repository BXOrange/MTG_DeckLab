"""Linked exile groups: one host, its Auras and its exact exile visits."""
from __future__ import annotations

from copy import copy

from .core import GameEffect, TriggeredAbility
from .battlefield_batches import start_exile_return_batch
from ..targeting import TargetSpec
from ...models.game.events import EventType
from ...models.game.game_object import Zone
from ...models.game.game_state import DelayedTrigger, TurnScopedTrigger


def _visit(obj):
    return (obj.instance_id, obj.zone_incarnation)


def _find_visit(context, visit):
    obj = context.state.find_object(visit[0])
    return obj if obj is not None and obj.zone_incarnation == visit[1] else None


class ReturnAttachedExileGroupEffect(GameEffect):
    """RULE 603.7c/303.4i: return the host, then its still-linked legal Auras."""

    def __init__(self, host_visit, aura_visits, counters=None, tapped=False, source=None):
        super().__init__(source)
        self.host_visit = host_visit
        self.aura_visits = list(aura_visits)
        self.counters = dict(counters or {})
        self.tapped = tapped

    def apply(self, context, targets=None):
        start_exile_return_batch(
            context.engine, [self.host_visit],
            entry_options={'tapped': self.tapped, 'entry_counters': self.counters},
            after_effects=[ReturnLinkedAurasEffect(self.aura_visits, source=self.source)],
            source=self.source,
        )


class ReturnLinkedAurasEffect(GameEffect):
    """Return the Aura batch only after the host's entry choices finish."""

    def __init__(self, aura_visits, source=None):
        super().__init__(source)
        self.aura_visits = list(aura_visits)

    def apply(self, context, targets=None):
        if not targets:
            return
        returned = targets[0]
        host_visit = _visit(returned)
        eligible = []
        # RULE 303.4i: determine the whole Aura batch against the prospective
        # owner-controller before any member's continuous effects can apply.
        for visit in self.aura_visits:
            aura = _find_visit(context, visit)
            if aura is None or aura.zone != Zone.EXILE or aura.is_token:
                continue
            prospective = copy(aura)
            prospective.controller_id = aura.owner_id
            if context.engine._attachment_legal(prospective, returned, check_control=False):
                eligible.append(visit)
        start_exile_return_batch(
            context.engine, eligible, entry_options={'attach_to': host_visit},
            source=self.source,
        )


class _SourceReleaseTrigger(TriggeredAbility):
    """A single delayed trigger with two alternative events (RULE 603.7b)."""

    def __init__(self, source_visit, effect, controller_id, source):
        super().__init__(EventType.UNTAPPED, [effect], controller_id=controller_id,
                         source=source, description="Tawnos's Coffin: Exilgruppe zurückbringen")
        self.source_visit = source_visit

    def check_trigger(self, event, context):
        if event.type not in (EventType.UNTAPPED, EventType.LEAVES_BATTLEFIELD):
            return False
        if event.get('instance_id') != self.source_visit[0]:
            return False
        # Both events are emitted while the departing/untapping visit still
        # exists; a later copy of the same card cannot release this group.
        return _find_visit(context, self.source_visit) is not None


class ExileAttachedGroupEffect(GameEffect):
    """Exile a fixed host/Aura batch, then install its delayed return."""

    def __init__(self, release='end', attached_host=False, remember_counters=False, source=None):
        super().__init__(source)
        self.release = release
        self.attached_host = attached_host
        self.remember_counters = remember_counters
        if not attached_host:
            self.target_spec = TargetSpec(kind='creature')

    def apply(self, context, targets=None):
        if self.attached_host:
            # The resolving ability is independent of its source, but "enchanted
            # creature" needs the last attachment relationship if the Aura left.
            expected_source = context.resolving_source_incarnation
            if (self.source.zone == Zone.BATTLEFIELD
                    and (expected_source is None or self.source.zone_incarnation == expected_source)):
                host = context.state.find_object(self.source.attached_to)
            else:
                item = context.resolving_stack_item
                relationship = getattr(item, 'source_attachment_lki', None)
                host = _find_visit(context, relationship) if relationship is not None else None
        else:
            host = targets[0] if targets else None
        if host is None or host not in context.state.permanents():
            return
        auras = [obj for obj in context.state.permanents()
                 if obj.attached_to == host.instance_id
                 and context.engine._attachment_kind(obj) == 'enchant']
        counters = dict(host.counters) if self.remember_counters else {}
        source_visit = (self.source.instance_id,
                        context.resolving_source_incarnation
                        if context.resolving_source_incarnation is not None
                        else self.source.zone_incarnation)
        controller = context.resolving_controller_id or self.source.controller_id
        # Capture membership before the first exile detaches the host's Auras.
        host_visit = (host.instance_id, host.zone_incarnation + 1)
        aura_visits = [(aura.instance_id, aura.zone_incarnation + 1) for aura in auras]
        context.exile(host)
        for aura in auras:
            context.exile(aura)
        effect = ReturnAttachedExileGroupEffect(
            host_visit, aura_visits, counters=counters,
            tapped=self.remember_counters, source=self.source,
        )
        if self.release == 'end':
            context.state.delayed_triggers.append(DelayedTrigger(
                controller, 'end', [effect], scope='any',
                description='Flickerform: Kreatur und Auren zurückbringen',
            ))
        else:
            # RULE 603.7a: install only now; an earlier untap/departure is not
            # retroactive. The existing persistent one-shot event watcher is
            # also used by Earthbend, rather than a second delayed scheduler.
            ability = _SourceReleaseTrigger(source_visit, effect, controller, self.source)
            context.state.turn_scoped_triggers.append(TurnScopedTrigger(
                ability, install_turn=None, once=True,
                bound_object_id=source_visit[0], bound_incarnation=source_visit[1],
            ))


EFFECT_FACTORIES = {
    'exile_attached_group': lambda p: ExileAttachedGroupEffect(
        release=p.get('release', 'end'), attached_host=bool(p.get('attached_host')),
        remember_counters=bool(p.get('remember_counters')),
    ),
}

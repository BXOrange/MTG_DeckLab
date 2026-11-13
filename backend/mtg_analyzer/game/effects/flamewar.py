"""Flamewar's upgrade, face-down intel exile, and owned intel recovery."""
from .core import GameEffect, _controller_of


def _same_visit(context, source):
    return (source is not None and source in context.state.permanents()
            and (context.resolving_source_incarnation is None
                 or source.zone_incarnation == context.resolving_source_incarnation))


class FlamewarUpgradeEffect(GameEffect):
    def apply(self, context, targets=None):
        if _same_visit(context, self.source):
            context.engine.add_counters(self.source, 1, "+1/+1", source=self.source)
            context.engine.transform_permanent(self.source)


class FlamewarIntelExileEffect(GameEffect):
    def apply(self, context, targets=None):
        controller = _controller_of(self.source, context)
        if controller is None:
            return
        count = max(0, int((context.trigger_event or {}).get("amount", 0) or 0))
        cards = list(reversed(controller.library[-count:])) if count else []
        with context.state.simultaneous():
            for obj in cards:
                context.engine.exile(obj, face_down=True)
                context.engine.add_counters(obj, 1, "intel", source=self.source)
        if _same_visit(context, self.source):
            context.engine.transform_permanent(self.source)


class FlamewarRecoverIntelEffect(GameEffect):
    def apply(self, context, targets=None):
        controller = _controller_of(self.source, context)
        if controller is None:
            return
        cards = [obj for player in context.state.players for obj in player.exile
                 if obj.owner_id == controller.id and obj.counters.get("intel", 0) > 0 and not obj.is_token]
        with context.state.simultaneous():
            for obj in cards:
                context.return_to_hand(obj)
                # RULE 122.2: counters cease to exist on changing zones, without being removed.
                obj.counters.clear()
                obj.controller_id = obj.owner_id
                obj.face_down_exile_viewers.clear()

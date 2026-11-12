"""Invasion of Tarkir's counted reveal and independently targeted reflexive trigger."""
from dataclasses import replace

from .core import GameEffect, _controller_of
from .damage_draw import DealDamageEffect
from ..continuations import choice, ANSWER_STR
from ...models.game.events import EventType, GameEvent


def _pool(rules, frame):
    player = rules.state.player_by_id(frame["player_id"])
    selected = {record["instance_id"] for record in frame["selected"]}
    return [obj for obj in player.hand if not obj.is_token and obj.has_subtype("Dragon") and obj.instance_id not in selected]


def _finish(rules, frame):
    player = rules.state.player_by_id(frame["player_id"])
    chosen = [obj for record in frame["selected"]
              if (obj := rules.state.find_object(record["instance_id"])) is not None
              and obj in player.hand and obj.zone_incarnation == record["incarnation"]]
    with rules.state.simultaneous():
        for obj in chosen:
            rules.state.reveal_card(obj, player.id)
    source = rules.state.find_object(frame["source_id"])
    # RULE 603.12: revealing zero cards still performs "reveal any number".
    rules.enqueue_reflexive_trigger([
        {"type": "tarkir_revealed_dragons_damage", "params": {
            "amount": len(chosen) + 2, "source_incarnation": frame["source_incarnation"], "source_id": frame["source_id"],
        }},
    ], source, event=GameEvent(EventType.SPELL_RESOLVED, source_zone_incarnation=frame["source_incarnation"]),
       controller_id=player.id)


def _offer(rules, frame):
    pool = _pool(rules, frame)
    if not pool:
        _finish(rules, frame)
        return
    rules.open_choice({**frame, "kind": "tarkir_reveal_dragons", "optional": True,
        "prompt": "Beliebig viele Drachenkarten zum Aufdecken wählen",
        "options": [{"id": "done", "label": "Auswahl abschließen"}, *[
            {"id": str(obj.instance_id), "instance_id": obj.instance_id,
             "incarnation": obj.zone_incarnation, "label": obj.name} for obj in pool]]})


@choice("tarkir_reveal_dragons", answer=ANSWER_STR, rule="603.12")
def _resume(rules, frame, answer):
    if answer is None or answer == "done":
        _finish(rules, frame)
        return
    offered = next((o for o in frame["options"] if o["id"] == answer), None)
    obj = rules.state.find_object(offered.get("instance_id")) if offered else None
    if obj not in _pool(rules, frame) or obj.zone_incarnation != offered.get("incarnation"):
        rules.open_choice(frame)
        raise ValueError("Choose a listed Dragon card or finish")
    _offer(rules, {**frame, "selected": [*frame["selected"], {
        "instance_id": obj.instance_id, "incarnation": obj.zone_incarnation,
    }]})


class TarkirRevealDragonsEffect(GameEffect):
    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        incarnation = context.resolving_source_incarnation
        _offer(context.engine, {"source_id": self.source.instance_id,
            "source_incarnation": self.source.zone_incarnation if incarnation is None else incarnation,
            "player_id": player.id, "selected": []})


class TarkirRevealedDragonsDamageEffect(DealDamageEffect):
    def __init__(self, amount=2, source_incarnation=None, source_id=None, source=None):
        super().__init__(amount=max(2, int(amount)), target_kind="any", source=source)
        self.source_incarnation = source_incarnation
        self.source_id = source_id
        self.target_spec = replace(self.target_spec, exclude_source=True)

    @property
    def target_specs(self):
        # RULE 400.7: a later battlefield visit of this physical card is
        # another object, so "other target" no longer excludes that visit.
        same = (self.source is not None and self.source.zone_incarnation == self.source_incarnation)
        return [replace(self.target_spec, exclude_source=same)]

    def apply(self, context, targets=None):
        source = self.source
        if source is None or source not in context.state.permanents() or source.zone_incarnation != self.source_incarnation:
            source_id = self.source_id if self.source_id is not None else getattr(source, "instance_id", None)
            self.source = context.state.zone_visit_sources.get((source_id, self.source_incarnation), source)
        try:
            super().apply(context, targets)
        finally:
            self.source = source

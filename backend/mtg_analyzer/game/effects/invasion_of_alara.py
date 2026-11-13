"""Alara's two-hit exile and the Maelstrom's resolution-time choices."""
from collections import Counter

from .core import GameEffect, _controller_of, _apply_effects_partitioned
from ..continuations import choice, ANSWER_STR
from ...models.game.game_object import Zone


_ALARA_HITS = 2
_ALARA_MAX_MANA_VALUE = 4
_MAELSTROM_COUNTERS = 3


def _hit(obj):
    return not obj.card.is_land and obj.card.converted_mana_cost <= _ALARA_MAX_MANA_VALUE


def _exiled_visits(context, hits):
    return [obj for obj, visit in context.latest_exiled_visits
            if obj.zone == Zone.EXILE and obj.zone_incarnation == visit and _hit(obj) == hits]


class AlaraExileEffect(GameEffect):
    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        visits, hits = [], []
        while player.library and len(hits) < _ALARA_HITS:
            obj = player.library[-1]
            context.engine.exile(obj)
            if obj.zone == Zone.EXILE:
                visits.append((obj, obj.zone_incarnation))
                if _hit(obj):
                    hits.append(obj)
        context.latest_exiled_visits = visits
        context.engine._request_resolution_play(player, hits, free=True, only_spells=True)


@choice("alara_take_hand", answer=ANSWER_STR, rule="608.2d")
def _resume_hand(rules, frame, answer):
    option = next((o for o in frame["options"] if o["id"] == answer), None)
    obj = rules.state.find_object(option["instance_id"]) if option else None
    if obj is None or obj.zone != Zone.EXILE or obj.zone_incarnation != option["incarnation"]:
        rules.open_choice(frame)
        raise ValueError("Choose one of the qualifying exiled cards")
    rules.return_to_hand(obj)


class AlaraTakeHandEffect(GameEffect):
    def apply(self, context, targets=None):
        pool = _exiled_visits(context, True)
        if len(pool) == 1:
            context.engine.return_to_hand(pool[0])
        elif pool:
            context.engine.open_choice({"kind": "alara_take_hand", "player_id": _controller_of(self.source, context).id,
                "prompt": "Eine der gefundenen Karten auf die Hand nehmen", "options": [
                    {"id": str(obj.instance_id), "label": obj.name, "instance_id": obj.instance_id,
                     "incarnation": obj.zone_incarnation} for obj in pool]})


class AlaraBottomRestEffect(GameEffect):
    def apply(self, context, targets=None):
        # The other qualifying hit stays exiled if neither hit was cast.
        # Only passed-over lands and expensive cards go back (MOM release notes).
        pool = _exiled_visits(context, False)
        while pool:
            obj = pool.pop(context.engine.random_int(len(pool)))
            context.engine.return_to_library(obj, "bottom")


class MaelstromArtifactEffect(GameEffect):
    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        context.engine._request_choose_objects(player, [o for o in player.hand if o.card.is_artifact],
            "put_onto_battlefield", count=1, optional=True, source=self.source,
            prompt="Optional eine Artefaktkarte aus deiner Hand ins Spiel bringen")


@choice("maelstrom_copy", answer=ANSWER_STR, rule="608.2d")
def _resume_copy(rules, frame, answer):
    option = next((o for o in frame["options"] if o["id"] == answer), None)
    obj = rules.state.find_object(option["instance_id"]) if option else None
    if (obj is None or obj not in rules.state.permanents() or obj.zone_incarnation != option["incarnation"]
            or obj.controller_id != frame["player_id"]):
        rules.open_choice(frame)
        raise ValueError("Choose a permanent you control")
    rules.copy_permanent(frame["player_id"], obj)


class MaelstromCopyEffect(GameEffect):
    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        pool = context.state.permanents_controlled_by(player.id)
        if pool:
            context.engine.open_choice({"kind": "maelstrom_copy", "player_id": player.id,
                "prompt": "Eine eigene bleibende Karte für die Spielsteinkopie wählen", "options": [
                    {"id": str(obj.instance_id), "label": obj.name, "instance_id": obj.instance_id,
                     "incarnation": obj.zone_incarnation} for obj in pool]})


def _offer_counters(rules, frame):
    pool = [o for o in rules.state.permanents_controlled_by(frame["player_id"]) if o.is_creature]
    if not pool:
        return  # RULE 609.3: with no creatures there is nothing to distribute.
    rules.open_choice({**frame, "kind": "maelstrom_counters",
        "prompt": f"+1/+1-Marke zuweisen (noch {frame['remaining']})", "options": [
            {"id": str(obj.instance_id), "label": obj.name, "instance_id": obj.instance_id,
             "incarnation": obj.zone_incarnation} for obj in pool]})


@choice("maelstrom_counters", answer=ANSWER_STR, rule="608.2d")
def _resume_counters(rules, frame, answer):
    option = next((o for o in frame["options"] if o["id"] == answer), None)
    obj = rules.state.find_object(option["instance_id"]) if option else None
    if (obj is None or obj not in rules.state.permanents() or not obj.is_creature
            or obj.controller_id != frame["player_id"] or obj.zone_incarnation != option["incarnation"]):
        rules.open_choice(frame)
        raise ValueError("Choose a creature you control")
    allocations = [*frame["allocations"], (obj.instance_id, obj.zone_incarnation)]
    if frame["remaining"] > 1:
        _offer_counters(rules, {**frame, "remaining": frame["remaining"] - 1, "allocations": allocations})
        return
    source = rules.state.find_object(frame["source_id"])
    # RULE 122.1: place the chosen distribution together, after the full
    # allocation, so later choices never see a partially boosted creature.
    placements = [_MaelstromCounterPlacement(instance_id, incarnation, amount, source)
                  for (instance_id, incarnation), amount in Counter(allocations).items()]
    depth = len(rules.state.deferred_effects)
    already_held = rules.state._batch_hold
    with rules.state.simultaneous():
        _apply_effects_partitioned(placements, rules.context, None, None, source=source)
        if rules.state.pending_choice is not None and not already_held:
            # Replacement choices may interrupt one recipient's placement.
            # Keep the batch together and resume the other recipients before
            # the spell moves on to destruction.
            rules.state.hold_batches()
            rules.state.deferred_effects.insert(depth, {"kind": rules.DEFERRED_BATCH_END})


class _MaelstromCounterPlacement(GameEffect):
    def __init__(self, instance_id, incarnation, amount, source):
        super().__init__(source)
        self.instance_id, self.incarnation, self.amount = instance_id, incarnation, amount

    def apply(self, context, targets=None):
        recipient = context.state.find_object(self.instance_id)
        if (recipient in context.state.permanents() and recipient.zone_incarnation == self.incarnation):
            context.engine.add_counters(recipient, self.amount, source=self.source)


class MaelstromCountersEffect(GameEffect):
    def apply(self, context, targets=None):
        _offer_counters(context.engine, {"player_id": _controller_of(self.source, context).id,
            "source_id": self.source.instance_id, "remaining": _MAELSTROM_COUNTERS, "allocations": []})

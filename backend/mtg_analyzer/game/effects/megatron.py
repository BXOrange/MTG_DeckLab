"""Megatron's optional conversion and sacrifice-triggered excess-damage split."""
from .core import GameEffect, _controller_of
from ..continuations import choice, ANSWER_STR
from ..targeting import TargetSpec
from ...models.game.events import EventType, GameEvent


def _same_visit(state, source, incarnation):
    return source is not None and source in state.permanents() and source.zone_incarnation == incarnation


@choice("megatron_convert_mana", answer=ANSWER_STR, rule="701.28")
def _resume_convert(rules, frame, answer):
    if answer != "convert":
        return
    source = rules.state.find_object(frame["source_id"])
    if not _same_visit(rules.state, source, frame["source_incarnation"]):
        return
    if rules.transform_permanent(source):
        amount = sum(rules.state.life_lost_this_turn.get(p.id, 0)
                     for p in rules.state.living_players() if p.id != frame["player_id"])
        rules.add_mana(rules.state.player_by_id(frame["player_id"]), "C", amount)


class MegatronConvertManaEffect(GameEffect):
    def apply(self, context, targets=None):
        incarnation = context.resolving_source_incarnation
        if incarnation is None:
            incarnation = self.source.zone_incarnation
        if not _same_visit(context.state, self.source, incarnation):
            return
        controller = _controller_of(self.source, context)
        context.engine.open_choice({"kind": "megatron_convert_mana", "player_id": controller.id,
            "source_id": self.source.instance_id, "source_incarnation": incarnation,
            "prompt": "Megatron umwandeln und farbloses Mana erzeugen?",
            "options": [{"id": "decline", "label": "Nicht umwandeln"}, {"id": "convert", "label": "Umwandeln"}]})


def _artifacts(rules, frame):
    return [obj for obj in rules.state.permanents_controlled_by(frame["player_id"])
            if "artifact" in obj.type_words and not obj.cant_be_sacrificed_this_turn
            and (obj.instance_id, obj.zone_incarnation) != (frame["source_id"], frame["source_incarnation"])]


@choice("megatron_sacrifice", answer=ANSWER_STR, rule="603.12")
def _resume_sacrifice(rules, frame, answer):
    if answer is None or answer == "decline":
        return
    offered = next((o for o in frame["options"] if o["id"] == answer), None)
    obj = rules.state.find_object(offered.get("instance_id")) if offered else None
    if obj not in _artifacts(rules, frame) or obj.zone_incarnation != offered.get("incarnation"):
        rules.open_choice(frame)
        raise ValueError("Choose a listed artifact or decline")
    amount = max(0, int(obj.mana_value or 0))
    visit = obj.zone_incarnation
    rules.put_into_graveyard(obj)
    if obj in rules.state.permanents() and obj.zone_incarnation == visit:
        return
    source = rules.state.find_object(frame["source_id"])
    rules.enqueue_reflexive_trigger([
        {"type": "megatron_split_damage", "params": {"amount": amount, "source_incarnation": frame["source_incarnation"]}},
        {"type": "megatron_excess_convert", "params": {"source_incarnation": frame["source_incarnation"]}},
    ], source, event=GameEvent(EventType.SPELL_RESOLVED, source_zone_incarnation=frame["source_incarnation"]),
       controller_id=frame["player_id"])


class MegatronSacrificeEffect(GameEffect):
    def apply(self, context, targets=None):
        controller = _controller_of(self.source, context)
        incarnation = context.resolving_source_incarnation
        frame = {"player_id": controller.id, "source_id": self.source.instance_id,
                 "source_incarnation": self.source.zone_incarnation if incarnation is None else incarnation}
        pool = _artifacts(context.engine, frame)
        if not pool:
            return
        context.engine.open_choice({**frame, "kind": "megatron_sacrifice", "optional": True,
            "prompt": "Ein anderes Artefakt für Megatron opfern?",
            "options": [{"id": "decline", "label": "Nicht opfern"}, *[
                {"id": str(obj.instance_id), "instance_id": obj.instance_id,
                 "incarnation": obj.zone_incarnation, "label": obj.name} for obj in pool]]})


class MegatronSplitDamageEffect(GameEffect):
    def __init__(self, amount=0, source_incarnation=None, source=None):
        super().__init__(source)
        self.amount = max(0, int(amount))
        self.source_incarnation = source_incarnation
        self.target_spec = TargetSpec(kind="creature")

    def apply(self, context, targets=None):
        target = targets[0] if targets else None
        if target is None:
            return
        context.recompute()
        dealer = self.source if _same_visit(context.state, self.source, self.source_incarnation) else (
            context.state.zone_visit_sources.get((getattr(self.source, "instance_id", None), self.source_incarnation), self.source))
        # RULE 120.4a: determine and redirect excess before replacement/prevention.
        excess = context.engine._excess_damage(target, self.amount, dealer)
        if context.trigger_event is not None:
            context.trigger_event["megatron_excess"] = excess > 0
        recipient = context.state.player_by_id(target.controller_id)
        with context.engine.damage_batch():
            context.engine.deal_damage(target, self.amount - excess, source=dealer)
            if excess:
                context.engine.deal_damage(recipient, excess, source=dealer)


class MegatronExcessConvertEffect(GameEffect):
    def __init__(self, source_incarnation=None, source=None):
        super().__init__(source)
        self.source_incarnation = source_incarnation

    def apply(self, context, targets=None):
        # A separate instruction lets the normal resolution frame wait for any
        # damage replacement choices before converting (BRO release notes).
        if ((context.trigger_event or {}).get("megatron_excess")
                and _same_visit(context.state, self.source, self.source_incarnation)):
            context.engine.transform_permanent(self.source)

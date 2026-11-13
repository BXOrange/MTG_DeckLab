"""Optimus Prime: bolster's chosen creature and its turn-scoped conversion trigger."""
from .core import GameEffect, TriggeredAbility, _controller_of
from .attachments_transforms import ReturnFromGraveyardTransformedEffect
from ..continuations import choice, ANSWER_INT
from ...models.game.events import EventType
from ...models.game.game_object import Zone
from ...models.game.game_state import TurnScopedTrigger


class OptimusConvertEffect(GameEffect):
    def __init__(self, source=None, source_incarnation=None):
        super().__init__(source)
        self.source_incarnation = source_incarnation

    def apply(self, context, targets=None):
        if (self.source is not None and self.source in context.state.permanents()
                and self.source.zone_incarnation == self.source_incarnation):
            context.engine.transform_permanent(self.source)


def _finish_bolster(rules, frame, chosen):
    source = rules.state.find_object(frame["source_id"])
    rules.add_counters(chosen, 2, "+1/+1", source=source)
    chosen.temp_keywords.add("trample")
    chosen_id, chosen_visit = chosen.instance_id, chosen.zone_incarnation

    def matches(event, context):
        obj = context.state.find_object(chosen_id)
        return (event.get("source_id") == chosen_id and event.get("combat")
                and event.get("is_player") and obj is not None
                and obj.zone == Zone.BATTLEFIELD and obj.zone_incarnation == chosen_visit)

    ability = TriggeredAbility(
        trigger_event=EventType.DAMAGE, condition=matches,
        effects=[OptimusConvertEffect(source, frame["source_incarnation"])],
        controller_id=frame["controller_id"], source=source,
        description="When that creature deals combat damage to a player this turn, convert Optimus Prime.",
    )
    # RULE 603.7b: the stated "this turn" duration allows repeated firings.
    rules.state.turn_scoped_triggers.append(TurnScopedTrigger(
        ability, rules.state.internal_turn.number, bound_object_id=chosen_id, bound_incarnation=chosen_visit))
    from ..continuous import recompute
    recompute(rules.state)


@choice("optimus_bolster", answer=ANSWER_INT, rule="701.39a")
def _resume_bolster(rules, frame, answer):
    offered = next((o for o in frame["options"] if o["instance_id"] == answer), None)
    if offered is None:
        rules.open_choice(frame)
        raise ValueError("Choose a listed creature with the least toughness")
    chosen = rules.state.find_object(answer)
    if chosen is not None and chosen in rules.state.permanents() and chosen.zone_incarnation == offered["incarnation"]:
        _finish_bolster(rules, frame, chosen)


class OptimusAttackBolsterEffect(GameEffect):
    def apply(self, context, targets=None):
        controller = _controller_of(self.source, context)
        if controller is None:
            return
        context.recompute()
        pool = [obj for obj in context.state.permanents_controlled_by(controller.id) if obj.is_creature]
        if not pool:
            return
        least = min(obj.toughness for obj in pool)
        pool = [obj for obj in pool if obj.toughness == least]
        frame = {"source_id": self.source.instance_id, "controller_id": controller.id,
                 "source_incarnation": context.resolving_source_incarnation
                    if context.resolving_source_incarnation is not None else self.source.zone_incarnation}
        if len(pool) == 1:
            _finish_bolster(context.engine, frame, pool[0])
            return
        context.engine.open_choice({**frame, "kind": "optimus_bolster", "player_id": controller.id,
            "optional": False, "prompt": "Verstärken 2: Kreatur mit geringster Widerstandskraft wählen",
            "options": [{"id": str(obj.instance_id), "instance_id": obj.instance_id,
                         "incarnation": obj.zone_incarnation, "label": obj.name} for obj in pool]})


class OptimusReturnConvertedEffect(ReturnFromGraveyardTransformedEffect):
    def apply(self, context, targets=None):
        source = self.source
        expected = (context.trigger_event or {}).get("graveyard_incarnation")
        if (source is not None and source.zone == Zone.GRAVEYARD
                and source.zone_incarnation == expected):
            context.engine.return_from_graveyard(source, "battlefield", controller_id=source.owner_id, transformed=True)

"""Triggered and graveyard keyword bodies shared by printed and granted abilities."""
from .core import EffectRegistry, GameEffect, TriggeredAbility, _controller_of
from ..continuations import choice
from ..targeting import TargetSpec
from ...models.game.events import EventType
from ...models.game.game_object import Zone


def _make_servo(rules, source, player_id, count):
    effect = EffectRegistry.create("create_token", {
        "count": count, "token_name": "Servo", "power": 1, "toughness": 1,
        "subtypes": ["Servo"], "is_artifact": True,
    })
    effect.source = source
    context = rules.context
    saved = context.acting_player_id
    try:
        context.acting_player_id = player_id
        effect.apply(context)
    finally:
        context.acting_player_id = saved


class FabricateEffect(GameEffect):
    def __init__(self, count, source):
        super().__init__(source)
        self.count = count

    def apply(self, context, targets=None):
        from ..continuous import counters_prohibited_for

        source = self.source
        player = _controller_of(source, context)
        incarnation = context.resolving_source_incarnation if context.resolving_source_incarnation is not None else source.zone_incarnation
        if (source not in context.state.permanents() or source.zone_incarnation != incarnation
                or counters_prohibited_for(context.state, source, "+1/+1")):
            _make_servo(context.engine, source, player.id, self.count)
            return
        context.engine.open_choice({
            "kind": "fabricate_choice", "player_id": player.id, "count": self.count,
            "source_id": source.instance_id, "incarnation": incarnation, "prompt": "Fabrizieren",
            "options": [{"id": "counters", "label": "+1/+1-Marken"},
                        {"id": "servos", "label": "Servo-Spielsteine"}],
        })


@choice("fabricate_choice", rule="702.123a")
def _resume_fabricate_choice(rules, pending, answer):
    from ..continuous import counters_prohibited_for

    if answer not in ("counters", "servos"):
        rules.open_choice(pending)
        raise ValueError("Choose counters or Servo tokens")
    source = rules.state.find_object(pending["source_id"])
    count = pending["count"]
    if (answer == "counters" and source in rules.state.permanents()
            and source.zone_incarnation == pending["incarnation"]
            and not counters_prohibited_for(rules.state, source, "+1/+1")):
        rules.add_counters(source, count, "+1/+1", source=source)
    else:
        _make_servo(rules, source, pending["player_id"], count)


class ModularEffect(GameEffect):
    def __init__(self, source):
        super().__init__(source)
        self.target_spec = TargetSpec(kind="creature", creature_filter={"card_type": "artifact"})

    def apply(self, context, targets=None):
        count = ((context.trigger_event or {}).get("counters") or {}).get("+1/+1", 0)
        if not count or not targets:
            return
        target = targets[0]
        context.engine.open_choice({
            "kind": "modular_choice", "player_id": _controller_of(self.source, context).id,
            "count": count, "target_id": target.instance_id, "incarnation": target.zone_incarnation,
            "prompt": f"{count} +1/+1-Marken auf {target.name} legen?",
            "optional": True, "options": [{"id": "counters", "label": "Marken legen"}],
        })


@choice("modular_choice", rule="702.43a")
def _resume_modular_choice(rules, pending, answer):
    if answer is None:
        return
    if answer != "counters":
        rules.open_choice(pending)
        raise ValueError("Choose the listed option")
    obj = rules.state.find_object(pending["target_id"])
    if obj in rules.state.permanents() and obj.zone_incarnation == pending["incarnation"]:
        rules.add_counters(obj, pending["count"], "+1/+1")


class PoisonousEffect(GameEffect):
    def __init__(self, count, source):
        super().__init__(source)
        self.count = count

    def apply(self, context, targets=None):
        event = context.trigger_event
        if event and event.get("is_player"):
            player = context.state.player_by_id(event.get("target_id"))
            if player is not None:
                context.add_player_counters(player, self.count, "poison", source=self.source)


class EncoreEffect(GameEffect):
    def apply(self, context, targets=None):
        from .battlefield_batches import start_token_batch

        controller = _controller_of(self.source, context)
        opponents = [p.id for p in context.state.living_players() if p.id != controller.id]
        if opponents:
            start_token_batch(
                context, [(controller.id, self.source.card, 1) for _ in opponents],
                self.source, controller.id, encore_defenders=opponents,
            )



def build_keyword_trigger(obj, name, n):
    """Build one instance of a RULE 702 trigger on the object carrying it."""
    if n is None:
        return []
    n = int(n)
    event = {
        "fabricate": EventType.ENTERS_BATTLEFIELD, "afterlife": EventType.DIES, "modular": EventType.DIES,
        "frenzy": EventType.ATTACKER_UNBLOCKED, "poisonous": EventType.DAMAGE,
    }[name]
    if name == "fabricate":
        effect = FabricateEffect(n, obj)
    elif name == "modular":
        effect = ModularEffect(obj)
    elif name == "poisonous":
        effect = PoisonousEffect(n, obj)
    elif name == "afterlife":
        effect = EffectRegistry.create("create_token", {
            "count": n, "token_name": "Spirit", "power": 1, "toughness": 1,
            "colors": ["W", "B"], "subtypes": ["Spirit"], "keywords": ["flying"],
        })
    else:
        from .counters_tokens import PumpEffect
        effect = PumpEffect(power=n, source=obj)
    effect.source = obj

    def condition(firing, _context):
        if name == "poisonous":
            return firing.get("source_id") == obj.instance_id and firing.get("combat") and firing.get("is_player")
        return firing.get("instance_id") == obj.instance_id

    return [TriggeredAbility(trigger_event=event, source=obj, effects=[effect], condition=condition,
                             description=f"{name.capitalize()} {n}")]

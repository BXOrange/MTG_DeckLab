"""Combat restrictions created as a spell or ability resolves."""
from .core import GameEffect, StaticAbility, _controller_of
from ..continuations import ANSWER_INT, choice


class FloatingCombatTaxEffect(GameEffect):
    def __init__(self, verb, amount, payment, duration, defender_scope=None):
        super().__init__()
        self.verb = verb
        self.amount = amount
        self.payment = payment
        self.duration = duration
        self.defender_scope = defender_scope

    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        if player is None:
            return
        # RULE 611.2a–c: the clock and protected player are fixed on resolution.
        amount = getattr(context.resolving_stack_item, "x", 0) if self.amount == "x" else self.amount
        context.state.floating_statics.append(StaticAbility(
            f"{self.verb}_tax", affects="all", source=self.source, duration=self.duration,
            duration_data={"player_id": player.id},
            params={"amount": amount, "payment": self.payment,
                    "defender_scope": self.defender_scope,
                    "all_defenders": self.defender_scope is None},
        ))


class EachPlayerMayCounterThenAttackBarEffect(GameEffect):
    def __init__(self, count):
        super().__init__()
        self.count = count

    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        if player is not None:
            _offer_counter_choice(context.engine, {
                "controller": player.id, "count": self.count,
                "source_id": self.source.instance_id if self.source is not None else None,
                "remaining": [p.id for p in context.state.living_players_apnap()],
                "chosen": [],
            })


def _offer_counter_choice(rules, data):
    from ..continuous import counters_prohibited_for

    state = rules.state
    # RULE 101.4: choices in APNAP order, then the instructions happen together.
    while data["remaining"]:
        player_id = data["remaining"].pop(0)
        options = [{"id": str(o.instance_id), "instance_id": o.instance_id, "label": o.name}
                   for o in state.permanents_controlled_by(player_id)
                   if o.is_creature and not counters_prohibited_for(state, o, "+1/+1")]
        if options:
            rules.open_choice({"kind": "counter_for_attack_bar", "player_id": player_id,
                               "optional": True, "options": options, "data": data,
                               "prompt": "+1/+1-Marken auf eine eigene Kreatur legen?"})
            return
    source = state.find_object(data["source_id"])
    with state.simultaneous():
        for player_id, iid in data["chosen"]:
            obj = state.find_object(iid)
            if obj is None:
                continue
            rules.add_counters(obj, data["count"], source=source)
            # RULE 118.12: accepting the payment counts even when a replacement changes what happens.
            state.floating_statics.append(StaticAbility(
                "cant_attack_defender", affects="all", source=source, duration="your_next_turn",
                duration_data={"player_id": data["controller"]},
                params={"attacker_controller_id": player_id, "defender_scope": "player_or_planeswalker"},
            ))


@choice("counter_for_attack_bar", answer=ANSWER_INT, rule="101.4")
def _resume_counter_choice(rules, pending, answer):
    data = pending["data"]
    if answer is not None:
        if not any(option["instance_id"] == answer for option in pending["options"]):
            rules.open_choice(pending)
            raise ValueError("choose a listed creature")
        data["chosen"].append((pending["player_id"], answer))
    _offer_counter_choice(rules, data)

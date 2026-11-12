"""The opponent chooses the sole creature exempt from a turn's block restriction."""
from .core import GameEffect, StaticAbility
from ..continuations import choice, ANSWER_INT
from ..targeting import TargetSpec


class WarCryRestriction(StaticAbility):
    def __init__(self, player_id, chosen_id, chosen_incarnation):
        super().__init__(layer="rules", duration="end_of_turn")
        self.player_id = player_id
        self.chosen_id = chosen_id
        self.chosen_incarnation = chosen_incarnation

    def prohibits_block(self, blocker):
        # RULE 611.2c: a rules restriction also reaches later arrivals and control changes.
        return blocker.controller_id == self.player_id and (
            blocker.instance_id != self.chosen_id or blocker.zone_incarnation != self.chosen_incarnation)


@choice("war_cry_creature", answer=ANSWER_INT, rule="608.2d")
def _resume_war_cry(rules, pending, answer):
    option = next((o for o in pending["options"] if o["instance_id"] == answer), None)
    if option is None:
        rules.open_choice(pending)
        raise ValueError("Choose a listed creature")
    rules.state.floating_statics.append(WarCryRestriction(
        pending["player_id"], answer, option["incarnation"]))


class WarCryEffect(GameEffect):
    def __init__(self, source=None):
        super().__init__(source)
        self.target_spec = TargetSpec(kind="opponent")

    def apply(self, context, targets=None):
        opponent = targets[0] if targets else None
        if opponent is None:
            return
        pool = [o for o in context.state.permanents_controlled_by(opponent.id) if o.is_creature]
        if not pool:
            # With no possible choice, later creatures still cannot block this turn.
            context.state.floating_statics.append(WarCryRestriction(opponent.id, None, None))
            return
        context.engine.open_choice({
            "kind": "war_cry_creature", "player_id": opponent.id, "optional": False,
            "prompt": "Kreatur wählen, die weiterhin blocken darf",
            "options": [{"id": str(o.instance_id), "instance_id": o.instance_id,
                         "incarnation": o.zone_incarnation, "label": o.name} for o in pool],
        })

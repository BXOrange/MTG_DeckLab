"""Fell Beast's Shriek: collect opponent choices before tapping and goading."""
from .core import GameEffect, _controller_of
from ..continuations import choice, ANSWER_INT


def _offer_shriek(rules, frame):
    remaining = list(frame["remaining_players"])
    while remaining:
        player_id = remaining.pop(0)
        pool = [o for o in rules.state.permanents_controlled_by(player_id) if o.is_creature]
        if not pool:
            continue
        rules.open_choice({
            **frame, "kind": "fell_beast_creature", "player_id": player_id,
            "remaining_players": remaining, "optional": False,
            "prompt": "Kreatur zum Tappen und Anstacheln wählen",
            "options": [{"id": str(o.instance_id), "instance_id": o.instance_id,
                         "incarnation": o.zone_incarnation, "label": o.name} for o in pool],
        })
        return
    # RULE 608.2e: all opponents choose before the chosen creatures are acted on.
    with rules.state.simultaneous():
        for visit in frame["selected"]:
            obj = rules.state.find_object(visit["instance_id"])
            if (obj is None or obj not in rules.state.permanents()
                    or obj.zone_incarnation != visit["incarnation"]):
                continue
            rules.set_tapped(obj, True)
            # An already-tapped creature is still goaded; tapping isn't a condition.
            rules.goad(obj, frame["goader_id"])


@choice("fell_beast_creature", answer=ANSWER_INT, rule="608.2e")
def _resume_shriek(rules, pending, answer):
    option = next((o for o in pending["options"] if o["instance_id"] == answer), None)
    if option is None:
        rules.open_choice(pending)
        raise ValueError("Choose a listed creature")
    _offer_shriek(rules, {**pending, "selected": [*pending["selected"], {
        "instance_id": answer, "incarnation": option["incarnation"],
    }]})


class FellBeastShriekEffect(GameEffect):
    def apply(self, context, targets=None):
        controller = _controller_of(self.source, context)
        if controller is None:
            return
        _offer_shriek(context.engine, {
            "goader_id": controller.id, "selected": [],
            "remaining_players": [p.id for p in context.state.living_players_apnap()
                                  if p.id != controller.id],
        })

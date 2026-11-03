"""RULE 601.2b: announce a mandatory choice of additional cost before casting."""
from functools import wraps
import inspect

from .continuations import choice


def choose_additional_cost(cast):
    signature = inspect.signature(cast)

    @wraps(cast)
    def announce(engine, player, obj, *args, **kwargs):
        cost = getattr(obj, "additional_cast_cost", None)
        alternatives = getattr(cost, "cast_alternatives", ())
        if not alternatives:
            return cast(engine, player, obj, *args, **kwargs)
        bound = signature.bind(engine, player, obj, *args, **kwargs)
        bound.apply_defaults()
        params = {k: v for k, v in bound.arguments.items() if k not in {"self", "player", "obj"}}
        index = params.get("additional_cost_index")
        if index is None:
            if engine.state.pending_choice:
                raise ValueError("Zuerst die offene Entscheidung abschließen")
            if not engine.can_cast(player, obj, assume_mana_available=True):
                raise ValueError("Zauberspruch kann nicht gewirkt werden")
            allowed = [i for i, branch in enumerate(alternatives)
                       if engine._can_pay_additional_cast_cost(player, obj, branch, x=params["x"],
                            sacrifice_choice=params["sacrifice_choice"], discard_choices=params["discard_choices"])]
            engine.rules.open_choice({
                "kind": "cast_cost_alternative", "player_id": player.id,
                "source": obj, "incarnation": obj.zone_incarnation, "kwargs": params,
                "prompt": "Zusätzliche Kosten wählen",
                "options": [{"id": str(i), "label": alternatives[i].label()} for i in allowed],
            })
            return None
        if type(index) is not int or not 0 <= index < len(alternatives):
            raise ValueError("Ungültige zusätzliche Kosten")
        obj.additional_cast_cost = alternatives[index]
        try:
            return cast(engine, player, obj, *args, **kwargs)
        finally:
            obj.additional_cast_cost = cost

    return announce


@choice("cast_cost_alternative", rule="601.2b")
def _resume_cast_cost_alternative(rules, payload, answer):
    allowed = {option["id"] for option in payload["options"]}
    if str(answer) not in allowed:
        rules.open_choice(payload)
        return
    obj = payload["source"]
    if obj.zone_incarnation != payload["incarnation"]:
        return
    params = dict(payload["kwargs"])
    params["additional_cost_index"] = int(answer)
    _pick_payment_object(rules, payload, params)


def _pick_payment_object(rules, payload, params):
    from .game_engine import GameEngine
    engine = GameEngine(rules.state, rules=rules)
    player = rules.state.player_by_id(payload["player_id"])
    obj = payload["source"]
    cost = obj.additional_cast_cost.cast_alternatives[params["additional_cost_index"]]
    if cost.sacrifice and params.get("sacrifice_choice") is None:
        pool = [o for o in rules.state.permanents_controlled_by(player.id)
                if engine._sacrifice_candidate(player, obj, cost.sacrifice, chosen_id=o.instance_id) is not None]
        key = "sacrifice_choice"
    elif cost.discard == 1 and params.get("discard_choices") is None:
        pool = [o for o in player.hand if o is not obj]
        key = "discard_choices"
    else:
        pool, key = [], None
    if len(pool) > 1:
        rules.open_choice({
            "kind": "cast_cost_object", "player_id": player.id,
            "source": obj, "incarnation": obj.zone_incarnation, "kwargs": params, "key": key,
            "prompt": "Karte für die zusätzlichen Kosten wählen",
            "options": [{"id": str(o.instance_id), "label": o.name} for o in pool],
        })
        return
    engine.cast_spell(player, obj, **params)


@choice("cast_cost_object", rule="601.2b")
def _resume_cast_cost_object(rules, payload, answer):
    if str(answer) not in {option["id"] for option in payload["options"]}:
        rules.open_choice(payload)
        return
    obj = payload["source"]
    if obj.zone_incarnation != payload["incarnation"]:
        return
    params = dict(payload["kwargs"])
    params[payload["key"]] = [int(answer)] if payload["key"] == "discard_choices" else int(answer)
    _pick_payment_object(rules, payload, params)

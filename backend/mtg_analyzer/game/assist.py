"""RULE 702.132: one other player may contribute to a spell's locked generic cost."""
from functools import wraps
from inspect import signature

from . import mana_potential
from .mana_abilities import restriction_predicate_for_cast
from ..models.mana.mana_cost import GENERIC, VARIABLE, ManaCost


def assistants(state, player):
    return [other for other in state.living_players() if other is not player and not other.is_dummy]


def generic(cost):
    return sum(symbol.amount for symbol in cost.symbols if symbol.kind in {GENERIC, VARIABLE})


def affordable_x(engine, player, obj):
    """Return the highest legal assisted X, or None when Assist is unavailable."""
    if "assist" not in obj.intrinsic_keywords or not assistants(engine.state, player):
        return None
    best = max((other.mana_pool.total() + mana_potential.max_potential_total(engine, other)
                for other in assistants(engine.state, player)), default=0)
    if not best:
        return None
    printed = ManaCost.from_card(obj.card)
    upper = 0
    if printed.has_variable:
        upper = best + player.mana_pool.total() + mana_potential.max_potential_total(engine, player)
    for x in range(upper, -1, -1):
        if not engine.can_cast(player, obj, x=x, assume_mana_available=True):
            continue
        cost = engine.effective_cast_cost(player, obj, x=x)
        if generic(cost) and mana_potential.is_castable_via_potential(engine, player, cost.reduce_generic_and_x(best)):
            return x
    return None


def can_offer(engine, player, obj):
    return affordable_x(engine, player, obj) is not None


def announce(cast):
    sig = signature(cast)

    @wraps(cast)
    def choose(engine, player, obj, *args, **kwargs):
        params = sig.bind(engine, player, obj, *args, **kwargs).arguments
        if params.get("face") != "assist":
            return cast(engine, player, obj, *args, **kwargs)
        if "assist" not in obj.intrinsic_keywords:
            raise ValueError("This spell does not have Assist")
        supplied = {key: value for key, value in params.items() if key not in {"self", "player", "obj"}}
        supplied["face"] = "front"
        validation = {key: value for key, value in supplied.items() if key in signature(engine.can_cast).parameters}
        if not engine.can_cast(player, obj, assume_mana_available=True, **validation):
            raise ValueError(f"{obj.name} cannot be announced with Assist")
        cost_args = {key: value for key, value in supplied.items() if key in signature(engine.effective_cast_cost).parameters}
        cost = engine.effective_cast_cost(player, obj, **cost_args)
        helpers = assistants(engine.state, player)
        if not generic(cost) or not helpers:
            raise ValueError("Assist needs a generic cost and another player")
        engine.state.pending_assist = {
            "player_id": player.id, "source_id": obj.instance_id, "visit": obj.zone_incarnation,
            "params": supplied, "cost": cost, "stage": "select",
        }
        engine.rules.open_choice({
            "kind": "assist_select", "player_id": player.id, "prompt": "Choose a player to assist",
            "options": [{"id": other.id, "label": other.name} for other in helpers]
                       + [{"id": "decline", "label": "Cancel"}],
        })

    return choose


def advance(rules, pending):
    """The helper gets the first mana window, then the caster, then the helper pays."""
    source = rules.state.find_object(pending["source_id"])
    if source is None or source.zone_incarnation != pending["visit"]:
        rules.state.pending_assist = None
        return
    helper = rules.state.player_by_id(pending["helper_id"])
    player = rules.state.player_by_id(pending["player_id"])
    if helper is None or helper.has_lost or player.has_lost:
        rules.state.pending_assist = None
        return
    stage = pending["stage"]
    payer = player if stage == "caster_mana" else helper
    options = [{"id": "continue", "label": "Done activating mana abilities"}]
    resource = "mana"
    if stage == "contribution":
        resource = "assist"
        options = [{"id": str(amount), "label": f"Pay {{{amount}}}"}
                   for amount in payable_contributions(rules, source, helper, player, pending)]
        options.append({"id": "decline", "label": "Cancel"})
    rules.state.pending_amount_payment = pending
    rules.open_choice({
        "kind": "amount_payment", "player_id": payer.id, "resource": resource,
        "prompt": "Assist", "source_id": source.instance_id, "source_name": source.name,
        "options": options,
    })


def payable_contributions(rules, source, helper, player, pending):
    cost = pending["cost"]
    predicate = restriction_predicate_for_cast(source, has_x=bool(pending["params"].get("x")))
    limit = min(generic(cost), helper.mana_pool.total())
    return [
        amount for amount in range(limit, -1, -1)
        if helper.mana_pool.can_pay(ManaCost.parse(f"{{{amount}}}"), allows_restriction=predicate)
        and player.mana_pool.can_pay(cost.reduce_generic_and_x(amount), life_available=player.life,
                                    allows_restriction=predicate)
    ]


def resume_payment(rules, pending, choice, answer):
    if answer == "decline":
        rules.state.pending_assist = None
        return
    if answer not in {option["id"] for option in choice["options"]}:
        raise ValueError("Choose an offered Assist option")
    if pending["stage"] != "contribution":
        pending["stage"] = "caster_mana" if pending["stage"] == "helper_mana" else "contribution"
        advance(rules, pending)
        return
    pending["amount"] = int(answer)
    pending["stage"] = "commit"


def commit(engine):
    pending = engine.state.pending_assist
    if pending is None or pending["stage"] != "commit":
        return False
    engine.state.pending_assist = None
    source = engine.state.find_object(pending["source_id"])
    if source is None or source.zone_incarnation != pending["visit"]:
        return True
    player = engine.state.player_by_id(pending["player_id"])
    helper = engine.state.player_by_id(pending["helper_id"])
    if pending["amount"] not in payable_contributions(engine.rules, source, helper, player, pending):
        raise ValueError("The Assist payment is no longer affordable")
    source._assist_payment = pending
    try:
        engine.cast_spell(player, source, **pending["params"])
    finally:
        source.__dict__.pop("_assist_payment", None)
    return True


def pay_contribution(engine, spell, item):
    pending = getattr(spell, "_assist_payment", None)
    if pending is None or not pending["amount"]:
        return
    helper = engine.state.player_by_id(pending["helper_id"])
    amount = pending["amount"]
    predicate = restriction_predicate_for_cast(spell, has_x=bool(item.x))
    helper.mana_pool.pay(ManaCost.parse(f"{{{amount}}}"), allows_restriction=predicate)
    spell.mana_spent_to_cast += amount

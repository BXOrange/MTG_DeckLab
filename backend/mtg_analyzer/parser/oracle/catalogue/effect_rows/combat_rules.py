"""Resolve-time costs and restrictions on combat declarations."""
from ...spec import EffectSpec
from .shared import EffectHandler, compile_clause


def _combat_tax(m):
    if m["participant"] != f"{m['verb']}ing":
        return None
    return [EffectSpec("floating_combat_tax", {
        "verb": m["verb"], "amount": "x" if m["amount"] == "x" else int(m["amount"]),
        "payment": "mana", "duration": "end_of_turn",
    })]


def _protecting_tax(m):
    return [EffectSpec("floating_combat_tax", {
        "verb": "attack", "amount": int(m["mana"] or m["life"]), "payment": "mana" if m["mana"] else "life",
        "duration": "your_next_turn",
        "defender_scope": "player_or_planeswalker" if m["walkers"] else "player",
    })]


def _counter_then_bar(m):
    return [EffectSpec("each_player_counter_then_attack_bar", {"count": int(m["count"])})]


ROWS = [
    EffectHandler("floating_global_combat_tax", compile_clause(
        r"this turn, creatures can't (?P<verb>attack|block) unless their controller pays \{(?P<amount>\d+|x)\}"
        r" for each (?P<participant>attacking|blocking) creature they control"
    ), _combat_tax),
    EffectHandler("floating_protecting_combat_tax", compile_clause(
        r"until your next turn, creatures can't attack you(?P<walkers> or planeswalkers you control)?"
        r" unless their controller pays (?:\{(?P<mana>\d+)\}|(?P<life>\d+) life) for each of those creatures"
    ), _protecting_tax),
    EffectHandler("each_player_counter_then_attack_bar", compile_clause(
        r"each player may put (?P<count>\d+) \+1/\+1 counters on a creature they control\. "
        r"if a player does, creatures that player controls can't attack you or planeswalkers you control until your next turn"
    ), _counter_then_bar),
]

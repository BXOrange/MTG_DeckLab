from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _protection_racket() -> list[AbilitySpec]:
    """Opponents decide in turn order inside one resolving upkeep trigger."""
    return [AbilitySpec("triggered", [EffectSpec("for_each", {
        "over": {"players": "each_opponent"}, "effects": [
            {"type": "reveal_top", "params": {}},
            {"type": "bind", "condition": {"kind": "mana_value", "of": "revealed", "min": 0}, "params": {
                "name": "mv", "amount": {"kind": "characteristic", "of": "revealed", "characteristic": "mana_value"},
                "effects": [{"type": "pay_cost_then", "params": {
                    "payer": "target", "cost": {"pay_life": "$mv"},
                    "prompt": "{revealed_card}: Lebenspunkte bezahlen?",
                    "effects": [{"type": "put_revealed_card", "params": {"destination": "exile"}}],
                    "else_effects": [{"type": "put_revealed_card", "params": {"destination": "hand"}}],
                }}],
            }},
        ],
    })], trigger={"event": "STEP_BEGIN", "filter": {"step": "upkeep"}, "phase_relation": "you"},
        raw_text="At the beginning of your upkeep, repeat the following process for each opponent in turn order. Reveal the top card of your library. That player may pay life equal to that card's mana value. If they do, exile that card. Otherwise, put it into your hand.")]


register("Protection Racket", _protection_racket)

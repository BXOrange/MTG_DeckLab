from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _palantir_of_orthanc() -> list[AbilitySpec]:
    """At the beginning of your end step, put an influence counter on Palantír
    of Orthanc and scry 2. Then target opponent may have you draw a card. If
    that player doesn't, you mill X cards, where X is the number of influence
    counters on Palantír of Orthanc, and that player loses life equal to the
    total mana value of those cards.

    A zero-cost optional choice belongs to the targeted opponent; the declined
    branch measures only the mill's moved cards, not the whole graveyard.
    """
    return [AbilitySpec("triggered", [
        EffectSpec("add_counters", {"count": 1, "kind": "influence"}),
        EffectSpec("scry", {"count": 2}),
        EffectSpec("pay_cost_then", {
            "cost": "{0}", "payer": "target", "target_kind": "opponent",
            "prompt": "Den Gegner eine Karte ziehen lassen?",
            "effects": [{"type": "draw", "params": {"count": 1}}],
            "else_effects": [
                {"type": "mill", "params": {"count": {
                    "kind": "counters", "counter": "influence", "of": "source",
                }}},
                {"type": "lose_life", "params": {
                    "target_kind": "player", "amount": {"kind": "moved_sum", "characteristic": "mana_value"},
                }},
            ],
        }),
    ], trigger={"event": EventType.STEP_BEGIN, "step": "end", "player": "you"})]


register("Palantír of Orthanc", _palantir_of_orthanc)

from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _thrull_parasite() -> list[AbilitySpec]:
    """Extort (Whenever you cast a spell, you may pay {W/B}. If you do, each opponent loses 1 life and you gain that much life.)
    {T}, Pay 2 life: Remove a counter from target nonland permanent.

    Extort reuses Crypt Ghast's paid drain; keyword recognition alone does
    not bind its payment trigger. Counter removal uses the shared grammar's
    exact-count primitive, with the controller choosing a kind on resolution.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{W/B}",
                "effects": [
                    {"type": "lose_life", "params": {"amount": 1, "selector": "each_opponent"}},
                    {"type": "gain_life", "params": {"count_selector": "life_lost_this_way"}},
                ],
            })],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("remove_counters", {"target_kind": "nonland_permanent", "exact_count": 1})],
            cost={"text": "{T}, Pay 2 life"},
        ),
    ]


register("Thrull Parasite", _thrull_parasite)

from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _aetherflux_conduit() -> list[AbilitySpec]:
    """Whenever you cast a spell, you get an amount of {E} (energy counters) equal to the amount of mana spent to cast that spell.
    {T}, Pay fifty {E}: Draw seven cards. You may cast any number of spells from your hand without paying their mana costs.

    — PLAY-ALL (Living Energy). The trigger measures the SPELL_CAST event's ``mana_spent``. **Simplification:** the free
    casts are armed for every nonland card in hand (`free_cast_from_hand` ``arm_all``) and last the rest of the turn
    rather than only while the ability resolves.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_player_counters", {
                "amount": {"kind": "trigger_event", "field": "mana_spent"}, "kind": "energy",
            })],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"}},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("draw", {"count": 7}),
                EffectSpec("free_cast_from_hand", {"arm_all": True}),
            ],
            cost={"text": "{t}, pay 50 {e}"},
        ),
    ]


register("Aetherflux Conduit", _aetherflux_conduit)

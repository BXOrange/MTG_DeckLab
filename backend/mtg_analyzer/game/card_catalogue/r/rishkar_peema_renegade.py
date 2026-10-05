from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rishkar_peema_renegade() -> list[AbilitySpec]:
    """When Rishkar enters, put a +1/+1 counter on each of up to two target
    creatures.
    Each creature you control with a counter on it has "{T}: Add {G}."

    — PLAY-ALL Step 2 (Raggadragga). The ETB is the parser's own claim,
    reproduced verbatim. The grant is `grant_mana_ability` (the parser's
    shape for "creatures you control have '{T}: Add {G}.'") narrowed by
    ``object_filter={"has_counter": True}`` — the kindless "with a counter on
    it" key, any counter kind (so a -1/-1 or a loyalty-like counter counts,
    as printed).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "count": 1, "kind": "+1/+1", "target_kind": "creature", "target_count": 2, "optional": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_mana_ability", {
                "mana": [{"G": 1}], "affects": "creatures_you_control",
                "object_filter": {"has_counter": True},
            })],
        ),
    ]


register("Rishkar, Peema Renegade", _rishkar_peema_renegade)

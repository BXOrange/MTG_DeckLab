from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


#: Charge counters at which Multivector Assault Mode is active.
MULTIVECTOR_LEVEL = 8


def _u_s_s_prometheus_prototype() -> list[AbilitySpec]:
    """Station (Tap another creature you control: Put charge counters equal to its power on this Spacecraft. Station only as a sorcery. It's an artifact creature at 4+.)
    4+ | Flying
    8+ | Multivector Assault Mode — Whenever U.S.S. Prometheus deals combat damage to an opponent, it deals that much damage to each other opponent.

    RULE 721 level rows: flying and the creature type change are the
    parser-claimed statics; the 8+ trigger is gated on the same charge
    counters (``source_counters``, RULE 603.4-style ``active_if``).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "keywords": ["flying"], "affects": "self", "min_level": 4, "level_counter": "charge",
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("type_change", {
                "add_types": ["creature"], "affects": "self", "min_level": 4,
                "level_counter": "charge", "power": 6, "toughness": 6,
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount_from_trigger_event": "amount", "selector": "each_other_opponent"})],
            trigger={
                "event": EventType.DAMAGE, "condition": {"subject": "self"},
                "filter": {"combat": True, "is_player": True}, "recipient_relation": "opponent",
                "active_if": {"kind": "source_counters", "counter": "charge", "min": MULTIVECTOR_LEVEL},
            },
        ),
    ]


register("U.S.S. Prometheus, Prototype", _u_s_s_prometheus_prototype)

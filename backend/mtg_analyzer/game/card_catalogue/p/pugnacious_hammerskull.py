from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _pugnacious_hammerskull() -> list[AbilitySpec]:
    """Whenever this creature attacks while you don't control another Dinosaur, put a stun counter on
    it. (If a permanent with a stun counter would become untapped, remove one from it instead.)

    — Tramplesaurus Rex deck batch. A self `ATTACKS` trigger whose "while you don't control another
    Dinosaur" is an intervening-if (RULE 603.4): `not` over a `control_count` of other Dinosaurs, on
    the trigger and again on the effect. The stun counter is `add_counters` (kind ``stun``) on itself.
    """
    gate = {"kind": "not", "condition": {"kind": "control_count", "min": 1, "selector": {
        "zone": "battlefield", "of": "you", "filter": {"subtype": "dinosaur", "not_reference": True},
    }}}
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"kind": "stun", "count": 1, "target_kind": None}, condition=gate)],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}, "active_if": gate},
        ),
    ]


register("Pugnacious Hammerskull", _pugnacious_hammerskull)

from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _armored_skyhunter() -> list[AbilitySpec]:
    """Flying
    Whenever this creature attacks, look at the top six cards of your
    library. You may put an Aura or Equipment card from among them onto
    the battlefield. If an Equipment is put onto the battlefield this
    way, you may attach it to a creature you control. Put the rest of
    those cards on the bottom of your library in a random order.

    Simplified: the found Aura/Equipment enters unattached — the "you may
    attach it to a creature you control" follow-up isn't modeled (no
    "dig hit, then optionally attach what was just found" primitive), and
    the rest go to exile instead of a random spot on the bottom of the
    library (`dig_until`'s own supported rest destinations).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("dig_until", {
                "criteria": {"type": ["Aura", "Equipment"]}, "hit_destination": "battlefield",
                "rest_destination": "exile",
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Armored Skyhunter", _armored_skyhunter)

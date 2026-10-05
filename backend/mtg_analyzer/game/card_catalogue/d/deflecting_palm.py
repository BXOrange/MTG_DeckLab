from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _deflecting_palm() -> list[AbilitySpec]:
    """The next time a source of your choice would deal damage to you this
    turn, prevent that damage. If damage is prevented this way, Deflecting
    Palm deals that much damage to that source's controller.

    — An instant, so the same `RequestPreventDamageSourceEffect` as Circle
    of Protection's activated ability, unqualified (``source_filter=None``
    — "a source of your choice" with no colour/type restriction) and
    carrying the new ``rider={"kind": "deal_damage_to_source_controller"}``,
    which `RulesEngine.apply_prevent_rider` fires with the real prevented
    amount once the chosen source's damage is actually stopped.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("request_prevent_damage_source", {
                "amount": "all",
                "rider": {"kind": "deal_damage_to_source_controller"},
            })],
        ),
    ]


register("Deflecting Palm", _deflecting_palm)

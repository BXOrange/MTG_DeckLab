from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lion_sash() -> list[AbilitySpec]:
    """{W}: Exile target card from a graveyard. If it was a permanent card,
    put a +1/+1 counter on this permanent.
    Equipped creature gets +1/+1 for each +1/+1 counter on this Equipment.
    Reconfigure {2}

    — Reconfigure's attach/unattach activated ability is synthesized by the
    keyword catalogue.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("exile_graveyard_card_counter_if_permanent", {})],
            cost={"mana": "{W}"},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "attached_permanent", "power": 1, "toughness": 1,
                "power_count": "plus_one_counters_on_self", "toughness_count": "plus_one_counters_on_self",
            })],
        ),
    ]


register("Lion Sash", _lion_sash)

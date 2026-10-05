from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _seraph_of_the_sword() -> list[AbilitySpec]:
    """Flying
    Prevent all combat damage that would be dealt to this creature.

    — PLAY-ALL (Calling All Angels). Flying is the keyword's. A standing `prevent_damage` shield (RULE 615) on itself
    whose ``source_filter`` is combat-only (the DAMAGE event's own ``combat`` flag).
    """
    return [
        AbilitySpec("replacement", [EffectSpec("prevent_damage", {
            "amount": "all", "to": "self", "source_filter": {"combat": True},
        })]),
    ]


register("Seraph of the Sword", _seraph_of_the_sword)

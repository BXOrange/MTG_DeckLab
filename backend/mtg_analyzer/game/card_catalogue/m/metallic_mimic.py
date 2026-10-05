from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _metallic_mimic() -> list[AbilitySpec]:
    """As this creature enters, choose a creature type.
    This creature is the chosen type in addition to its other types.
    Each other creature you control of the chosen type enters with an additional +1/+1 counter on it.

    — PLAY-ALL (Calling All Angels). The type choice and the self type are the parser's. The counters are the
    `extra_etb_counter` static filtered by ``subtype_from_source`` (the type the Mimic chose), excluding itself.
    """
    return [
        AbilitySpec("enter_replacement", [EffectSpec("choose_creature_type_on_enter", {})]),
        AbilitySpec("static", [EffectSpec("type_change", {"affects": "self", "add_subtypes_from_source": True})]),
        AbilitySpec("static", [EffectSpec("extra_etb_counter", {
            "kind": "+1/+1", "count": 1, "filter": {"subtype_from_source": True}, "other": True,
        })]),
    ]


register("Metallic Mimic", _metallic_mimic)

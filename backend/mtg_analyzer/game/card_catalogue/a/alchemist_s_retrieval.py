from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _alchemists_retrieval() -> list[AbilitySpec]:
    """Return target nonland permanent [you control] to its owner's hand.
    (Cleave {1}{U} — not modeled.)

    — Alchemist's Retrieval. The base (non-cleave) mode via `return_to_hand`
    with ``nonland_permanent_you_control``. Cleave (RULE 702.150 — an
    alternative cost that removes the bracketed words, here broadening the
    target to any nonland permanent) has no parser/engine support yet;
    documented drop.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_to_hand", {
                "target_kind": "nonland_permanent_you_control",
            })],
        )
    ]


register("Alchemist's Retrieval", _alchemists_retrieval)

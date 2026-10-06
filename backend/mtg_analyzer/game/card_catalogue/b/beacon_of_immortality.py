from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _beacon_of_immortality() -> list[AbilitySpec]:
    """Double target player's life total. Shuffle Beacon of Immortality into its owner's library.

    — PLAY-ALL (Hope to the last). Doubling is a `gain_life` on the targeted player of an amount equal to their current
    life total (the ``resource`` amount read off the ``target`` referent; a negative total gains nothing), then Beacon of
    Unrest's `shuffle_self_into_library`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("gain_life", {
                    "target_kind": "player", "amount": {"kind": "resource", "resource": "life", "of": "target"},
                }),
                EffectSpec("shuffle_self_into_library", {}),
            ],
        ),
    ]


register("Beacon of Immortality", _beacon_of_immortality)

from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dismantling_wave() -> list[AbilitySpec]:
    """For each opponent, destroy up to one target artifact or enchantment
    that player controls.
    Cycling {6}{W}{W}
    When you cycle this card, destroy all artifacts and enchantments.

    — Dismantling Wave. Simplified to a single "destroy up to one target
    artifact or enchantment" (dropping the "for each opponent" multiplayer
    scaling — no card in this pool needs per-opponent multi-target
    scaling yet). Cycling's own mass "destroy all artifacts and
    enchantments" is now real (RULE 702.28/702.29's "Discard this card"
    activation cost, `game/costs.py`'s ``discard_self``) — a hand-zone
    `AbilitySpec("activated", ...)` alongside the spell-effect one below,
    reusing the already-existing mass-destroy selector.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy", {"target_kind": "permanent", "optional": True})],
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("destroy", {"selector": "all_artifacts"}),
                EffectSpec("destroy", {"selector": "all_enchantments"}),
            ],
            cost={"text": "{6}{W}{W}, Discard this card"},
        ),
    ]


register("Dismantling Wave", _dismantling_wave)

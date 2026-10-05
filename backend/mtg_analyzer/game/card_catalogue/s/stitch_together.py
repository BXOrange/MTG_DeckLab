from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "seven or more cards in your graveyard" — the printed Threshold (RULE 702.xxx ability word).
_THRESHOLD = 7


def _stitch_together() -> list[AbilitySpec]:
    """Return target creature card from your graveyard to your hand.
    Threshold — Return that card from your graveyard to the battlefield instead
    if there are seven or more cards in your graveyard.

    — PLAY-ALL Step 2 (Oops! All Night's Whispers). The parser's own
    `return_from_graveyard` (to hand) plus the new ``destination_if`` swap: when
    the `control_count` over your graveyard (``min 7``, the target still counted)
    holds as it resolves, the one chosen target goes to the battlefield instead —
    "instead" with a single target, which two gated effects could not express.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_creature", "destination": "hand",
                "destination_if": {
                    "condition": {
                        "kind": "control_count", "selector": {"zone": "graveyard", "of": "you"}, "min": _THRESHOLD,
                    },
                    "destination": "battlefield",
                },
            })],
        ),
    ]


register("Stitch Together", _stitch_together)

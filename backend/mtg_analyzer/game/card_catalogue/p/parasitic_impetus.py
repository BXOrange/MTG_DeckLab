from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# Silverquill — the Impetus Aura cycle (Crimson Vow Commander). Each is
# "Enchant creature" (folds in from the RULE 702.5 keyword catalogue) + a
# "gets +N/+N and is goaded" static + one more clause the parser can't
# claim on its own. See PAR-60.
# ---------------------------------------------------------------------------


def _parasitic_impetus() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature gets +2/+2 and is goaded.
    Whenever enchanted creature attacks, its controller loses 2 life and you
    gain 2 life.

    — Parasitic Impetus. The static (`anthem` + `goaded`, both scoped
    ``attached_permanent``) the parser already claims, re-authored here
    because a registered card takes its whole spec set from this file. The
    attack trigger's "its controller" is the enchanted creature (RULE
    303.4c) → `LoseLifeEffect.selector="attached_permanent_controller"`."""
    IMPETUS_DRAIN = 2
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 2, "toughness": 2}),
                EffectSpec("goaded", {"affects": "attached_permanent"}),
            ],
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("lose_life", {
                    "amount": IMPETUS_DRAIN, "selector": "attached_permanent_controller",
                }),
                EffectSpec("gain_life", {"amount": IMPETUS_DRAIN}),
            ],
            trigger={"event": "ATTACKS", "condition": {"subject": "attached_permanent"}},
        ),
    ]


register("Parasitic Impetus", _parasitic_impetus)

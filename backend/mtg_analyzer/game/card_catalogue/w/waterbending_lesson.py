from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# PAR-30 — Waterbend (RULE 701.67) residue: the remaining per-card bodies.
# The shared "waterbend {X}" announcement (v215) folds the {X} into the
# spell's total and stamps `GameObject.x_paid`; each body below is bespoke.
# ---------------------------------------------------------------------------


def _waterbending_lesson() -> list[AbilitySpec]:
    """Draw three cards. Then discard a card unless you waterbend {2}.

    — RULE 118.3 resolve-time pay-or-discard: `pay_cost_then` with an
    ``else_effects`` discard, the cost being the waterbend {2} (modeled as a
    plain {2}, the same documented-simplification drop of the "tap your
    artifacts and creatures to help" helper as every other waterbend cost).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("draw", {"count": 3}),
                EffectSpec("pay_cost_then", {
                    "cost": "{2}",
                    "effects": [],
                    "else_effects": [{"type": "discard", "params": {"count": 1}}],
                    "prompt": "Wasserbändige {2}, sonst wirf eine Karte ab.",
                }),
            ],
        ),
    ]


register("Waterbending Lesson", _waterbending_lesson)

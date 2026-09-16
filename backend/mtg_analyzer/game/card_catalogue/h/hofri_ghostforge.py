from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Hofri Ghostforge (dies -> exile -> Spirit copy token) — PAR-60
# ===========================================================================
# New `hofri_ghostforge_dies` effect (reuse `copy_permanent` with
# ``add_subtypes=["Spirit"]``). The Spirit anthem static folds in from the
# parser (re-added). Documented simplification: the copy token's own "when
# this token leaves the battlefield, return the exiled card" rider dropped.


def _hofri_ghostforge() -> list[AbilitySpec]:
    """Spirits you control get +1/+1 and have trample and haste.
    Whenever another nontoken creature you control dies, exile it. If you
    do, create a token that's a copy of that creature, except it's a Spirit
    in addition to its other types and it has "When this token leaves the
    battlefield, return the exiled card to its owner's graveyard."""
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {
                    "power": 1, "toughness": 1, "affects": "creatures_you_control",
                    "subtype": "Spirit",
                }),
                EffectSpec("grant_keyword", {
                    "keywords": ["trample", "haste"], "affects": "creatures_you_control",
                    "subtype": "Spirit",
                }),
            ],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("hofri_ghostforge_dies", {})],
            trigger={"event": EventType.DIES,
                     "condition": {"subject": "group", "controller": "you",
                                   "type": "creature", "nontoken": True, "other": True}},
        ),
    ]


register("Hofri Ghostforge", _hofri_ghostforge)

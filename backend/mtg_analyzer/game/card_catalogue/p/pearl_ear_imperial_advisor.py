from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Pearl-Ear, Imperial Advisor (affinity for Auras + aura-cast
# draw) — PAR-60
# ===========================================================================
# Reuse of `cost_reduction` (``spell_type`` + ``per`` count_selector) for
# "affinity for Auras" and Kor Spiritdancer's own "whenever you cast an Aura
# spell" group trigger for the draw. Documented simplification: the draw's
# "that targets a modified permanent you control" narrowing is dropped.


def _pearl_ear_imperial_advisor() -> list[AbilitySpec]:
    """Lifelink (folds in).
    Enchantment spells you cast have affinity for Auras. (They cost {1} less
    to cast for each Aura you control.)
    Whenever you cast an Aura spell that targets a modified permanent you
    control, draw a card."""
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "your_spells", "generic": 1,
                "spell_type": "enchantment", "per": "auras_you_control",
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={"event": EventType.SPELL_CAST,
                     "condition": {"subject": "group", "subtypes": ["aura"],
                                   "controller": "you"}},
        ),
    ]


register("Pearl-Ear, Imperial Advisor", _pearl_ear_imperial_advisor)

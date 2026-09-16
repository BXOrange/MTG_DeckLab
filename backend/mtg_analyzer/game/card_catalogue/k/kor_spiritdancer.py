from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Silverquill Influence: Auras and "enchantments you control"
# ===========================================================================
#
# Shared shapes: a static bonus scoped ``affects="attached_permanent"`` (the
# Aura's own buff, RULE 303.4c), and "for each Aura you control" counts via
# the new ``auras_you_control`` `continuous.count_selector` and the
# ``auras_attached_to_self`` per-object `_pt_mod_count` selector (the Aura
# sibling of ``equipment_attached_to_self``). "Enchant creature" itself keeps
# coming from the RULE 702.5 keyword catalogue even for a registered card.


def _kor_spiritdancer() -> list[AbilitySpec]:
    """This creature gets +2/+2 for each Aura attached to it.
    Whenever you cast an Aura spell, you may draw a card."""
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "self", "power": 2, "toughness": 2,
                "power_count": "auras_attached_to_self",
                "toughness_count": "auras_attached_to_self",
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "subtypes": ["aura"], "controller": "you"},
            },
            optional=True,
        ),
    ]


register("Kor Spiritdancer", _kor_spiritdancer)

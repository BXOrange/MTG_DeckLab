from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _timely_ward() -> list[AbilitySpec]:
    """You may cast this spell as though it had flash if it targets a commander.
    Enchant creature
    Enchanted creature has indestructible.

    — Timely Ward. The conditional-flash clause (MEC-7) is
    `conditional_flash={"targets_a_commander": True}`, checked live at cast
    time against the caster's actual chosen target
    (`game/condition_query.py`'s `conditional_flash_holds`); the segmenter
    recognizes this exact template too (`_CONDITIONAL_FLASH_IF_TARGETS_
    COMMANDER_RE`), but only on the instant/sorcery `allow_spell_effect`
    path — an Aura like this one still needs the hand-authored entry. Rides
    on this same spec regardless of which one carries the real (attach-
    target) effects, same "may ride on any spec" idiom `additional_cost`
    uses.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"affects": "attached_permanent", "keywords": ["indestructible"]})],
            conditional_flash={"targets_a_commander": True},
        )
    ]


register("Timely Ward", _timely_ward)

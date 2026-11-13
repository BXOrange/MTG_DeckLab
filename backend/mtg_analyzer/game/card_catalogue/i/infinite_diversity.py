from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register
from ...creature_type_counts import CREATURE_TYPES_AMONG_NON_BORG_CREATURES_YOU_CONTROL


def _infinite_diversity() -> list[AbilitySpec]:
    """Federation — Exile target instant or sorcery card from your graveyard. Copy that card X times, where X is the
    number of creature types among non-Borg creatures you control. You may cast the copies without paying their mana
    costs. Exile Infinite Diversity.

    — MEC-143. Mizzix's Mastery's exile of the targeted card and its trailing self-exile, with `copy_exiled_card_x_times`
    (the counted sibling of Blue Mage's Cane's ``copy_imprinted_card`` copy) between them: X copies of the exiled card
    are offered as one repeated free-cast window (RULE 608.2g). X is measured when the copies are made (RULE 608.2h),
    after the exile. Sorcery speed by card type; the Federation ability word has no rules meaning (RULE 207.2c).
    """
    return [
        AbilitySpec("spell_effect", [
            EffectSpec("exile", {"target_kind": "graveyard_instant_or_sorcery"}),
            EffectSpec("copy_exiled_card_x_times", {
                "count": {"kind": "count_selector", "selector": CREATURE_TYPES_AMONG_NON_BORG_CREATURES_YOU_CONTROL},
                "free": True,
            }),
            EffectSpec("exile", {"target_kind": None}),
        ]),
    ]


register("Infinite Diversity", _infinite_diversity)

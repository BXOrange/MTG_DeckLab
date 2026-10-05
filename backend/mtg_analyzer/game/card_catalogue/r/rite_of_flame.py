from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rite_of_flame() -> list[AbilitySpec]:
    """Add {R}{R}, then add {R} for each card named Rite of Flame in each
    graveyard.

    — Rite of Flame. Two halves of one `AddManaEffect`: the flat ``{R}{R}``
    as printed symbols, plus the board-reading bonus via the new
    ``amount_selector`` (`continuous.count_selector`'s
    ``cards_named_source_in_all_graveyards`` — a cross-player aggregate like
    the existing ``total_rad_counters_among_players``, but name-keyed).

    The name comes from the effect's **own source object**, never from a
    free-text literal in the spec — putting an arbitrary card name through
    the spec boundary would buy nothing and widen it. The resolving copy is
    on the stack rather than in a graveyard, so it never counts itself.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("add_mana", {
                "colors": ["R", "R"],
                "color": "R",
                "amount_selector": "cards_named_source_in_all_graveyards",
            })],
        ),
    ]


register("Rite of Flame", _rite_of_flame)

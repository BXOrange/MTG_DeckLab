from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _aluren() -> list[AbilitySpec]:
    """Any player may cast creature spells with mana value 3 or less
    without paying their mana costs and as though they had flash.

    — Aluren, MEC-43 round 4G. A standing, board-wide free-cast permission
    scoped to **any** player, not just this enchantment's own controller —
    the first free-cast grant in this engine not scoped to one controller.
    Modeled as a genuine standing permission (`continuous.has_standing_
    free_cast_permission`/`standing_free_cast_grants_flash`, `EffectSpec(
    "free_cast_permission", ...)`), consulted live by `GameEngine.can_cast`
    and offered by `_offer_cast`/`_castable_now_or_via_potential` (the same
    "second, independent payment method alongside the plain mana-cost one"
    idiom MEC-15 already built for a per-object `free_cast_condition`) —
    not an armed per-card flag, since Aluren covers every qualifying
    creature spell in every hand at the table, not one specific card.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("free_cast_permission", {
                "creature_only": True,
                "max_mana_value": 3,
                "any_player": True,
                "grants_flash": True,
            })],
        )
    ]


register("Aluren", _aluren)

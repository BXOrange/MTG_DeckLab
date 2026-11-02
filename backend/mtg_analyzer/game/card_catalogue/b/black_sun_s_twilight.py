from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "If X is 5 or more" (the card's own threshold, RULE 107.3).
_REANIMATE_X_THRESHOLD = 5


def _black_sun_s_twilight() -> list[AbilitySpec]:
    """Up to one target creature gets -X/-X until end of turn. If X is 5 or more, return a creature card with mana value X or less from your graveyard to the battlefield tapped.

    Same shape as White Sun's Twilight: X-scaled effects on one spell plus an ``x_paid`` gate. The shrink is a
    targeted ``pump`` of ``-x/-x`` with an optional ("up to one") target; the reanimation is a non-targeted
    graveyard `search` (the creature is chosen on resolution, RULE 608.2c) bounded by the spell's own X
    (``max_mana_value: "x"``) and entering tapped.
    """
    return [AbilitySpec("spell_effect", [
        EffectSpec("pump", {"power": "-x", "toughness": "-x", "target_kind": "creature", "optional": True}),
        EffectSpec("search", {
            "criteria": {"type": "Creature", "max_mana_value": "x"},
            "destination": "battlefield_tapped", "zones": ["graveyard"], "optional": False,
        }, condition={"kind": "x_paid", "min": _REANIMATE_X_THRESHOLD}),
    ])]


register("Black Sun's Twilight", _black_sun_s_twilight)

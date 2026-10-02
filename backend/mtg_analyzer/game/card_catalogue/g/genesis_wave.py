from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: RULE 110.4 — every permanent type, lands included ("permanent cards").
_PERMANENT_TYPES = ["creature", "artifact", "enchantment", "planeswalker", "battle", "land"]


def _genesis_wave() -> list[AbilitySpec]:
    """Reveal the top X cards of your library. You may put any number of
    permanent cards with mana value X or less from among them onto the
    battlefield. Then put all cards revealed this way that weren't put onto the
    battlefield into your graveyard.

    — PLAY-ALL Step 2 (Raggadragga). PAR-144's `inspect_top_choose` with ``x``
    (refused by the grammar on purpose, so authored here): ``max_picks: all``
    (any number), the permanent-types criteria bounded by the announced X, and
    the unpicked cards to the graveyard.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("inspect_top_choose", {
                "count": "x", "action": "library_to_battlefield", "optional": True, "max_picks": "all",
                "criteria": {"type": list(_PERMANENT_TYPES), "max_mana_value": "x"},
                "rest_destination": "graveyard",
            })],
        ),
    ]


register("Genesis Wave", _genesis_wave)

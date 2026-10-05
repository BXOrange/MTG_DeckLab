from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _grapple_with_the_past() -> list[AbilitySpec]:
    """Mill three cards, then you may return a creature or land card from your graveyard to your hand.

    — PLAY-ALL Step 2 (Sultai Arisen). `mill` then a non-targeting, optional graveyard pick (``pick``: chosen on
    resolution, after the mill, so the milled cards are eligible — RULE 608.2d) over the new ``creature_or_land``
    graveyard filter.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "mill", "params": {"count": 3}},
                {"type": "return_from_graveyard", "params": {
                    "target_kind": "graveyard_creature_or_land", "destination": "hand",
                    "optional": True, "pick": True,
                }},
            ]})],
        ),
    ]


register("Grapple with the Past", _grapple_with_the_past)

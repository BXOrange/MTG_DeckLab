from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tannuk_steadfast_second() -> list[AbilitySpec]:
    """Other creatures you control have haste.
    Artifact cards and red creature cards in your hand have warp {2}{R}. (You may cast a card from your hand for its warp cost. Exile that permanent at the beginning of the next end step, then you may cast it from exile on a later turn.)
    """
    return [AbilitySpec("static", [
        EffectSpec("grant_keyword", {"affects": "other_creatures_you_control", "keywords": ["haste"]}),
        EffectSpec("grant_warp", {"cost": "{2}{R}", "filter": {
            "any_of": [{"card_type": "artifact"}, {"card_type": "creature", "color": "R"}],
        }}),
    ])]


register("Tannuk, Steadfast Second", _tannuk_steadfast_second)

from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _legions_to_ashes() -> list[AbilitySpec]:
    """Exile target nonland permanent an opponent controls and all tokens that player controls with the same name as that permanent.

    — PLAY-ALL (Revival Trance). New `exile_same_name_tokens` (Maelstrom Pulse's name-fixing shape, exile, tokens only);
    the target itself is always exiled.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("exile_same_name_tokens", {"target_kind": "nonland_permanent_you_dont_control"})],
        ),
    ]


register("Legions to Ashes", _legions_to_ashes)

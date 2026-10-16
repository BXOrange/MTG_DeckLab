from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _seedborn_muse() -> list[AbilitySpec]:
    """RULE 502.3: untap with every other player's turn-based untap action."""
    return [AbilitySpec("static", [EffectSpec("untap_each_untap_step", {"affects": "permanents_you_control"})])]


register("Seedborn Muse", _seedborn_muse)

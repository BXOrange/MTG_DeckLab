from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ruination() -> list[AbilitySpec]:
    """Destroy all nonbasic lands.

    MEC-12 fourth pass — `effects.DestroyEffect`'s existing
    ``selector="all_lands"`` mass-wipe path, narrowed by the new
    ``filter={"nonbasic": True}`` key (mirrors ``max_mana_value``'s
    selector+filter split for every other qualified board wipe).
    """
    return [AbilitySpec("spell_effect", [EffectSpec("destroy", {
        "selector": "all_lands", "filter": {"nonbasic": True},
    })])]


register("Ruination", _ruination)

from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _shimmer_myr() -> list[AbilitySpec]:
    """Flash
    You may cast artifact spells as though they had flash.

    — Keen Engineering deck batch. Flash is the keyword; the standing permission is the existing
    `flash_permission` static with an ``artifact`` type filter (Gandalf the White's shape).
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "flash"}),
        AbilitySpec("static", [EffectSpec("flash_permission", {"type_filter": ["artifact"]})]),
    ]


register("Shimmer Myr", _shimmer_myr)

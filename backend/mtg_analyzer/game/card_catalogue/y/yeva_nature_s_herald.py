from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _yeva_nature_s_herald() -> list[AbilitySpec]:
    """Flash
    You may cast green creature spells as though they had flash.

    — Tramplesaurus Rex deck batch. Flash is the keyword; the permission is `flash_permission` with
    ``creature_only`` and the new ``color`` filter (the card's colour identity contains it).
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "flash"}),
        AbilitySpec("static", [EffectSpec("flash_permission", {"creature_only": True, "color": "G"})]),
    ]


register("Yeva, Nature's Herald", _yeva_nature_s_herald)

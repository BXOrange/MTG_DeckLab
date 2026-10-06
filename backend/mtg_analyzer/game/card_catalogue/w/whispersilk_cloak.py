from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _whispersilk_cloak() -> list[AbilitySpec]:
    """Equipped creature can't be blocked and has shroud. (It can't be the target of spells or abilities.)
    Equip {2}

    — PLAY-ALL (Death Toll). Equip is the keyword catalogue's; "can't be blocked" is the synthetic flag keyword
    ``cant_be_blocked`` (as on Herald of Secret Streams), granted to the equipped creature alongside Shroud.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"affects": "attached_permanent", "keywords": ["cant_be_blocked", "shroud"]})],
        ),
    ]


register("Whispersilk Cloak", _whispersilk_cloak)

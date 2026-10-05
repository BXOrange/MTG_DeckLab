from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _whirlwing_stormbrood() -> list[AbilitySpec]:
    """Flash
    Flying
    You may cast sorcery spells and Dragon spells as though they had flash.

    — PLAY-ALL Step 2 (Temur Roar). Flash/Flying are printed keywords. The standing permission is the shipped
    `flash_permission` static (Teferi, Time Raveler's sorcery filter) whose ``type_filter`` now also accepts a
    subtype word read off the card's printed type line. Registered under the combined name too. The Omen half
    (Dynamic Soar, RULE 720) is cast through the Adventure path and binds from its own parsed text; resolving
    it shuffles the card into the library (`RulesEngine._is_omen_card`) rather than exiling it.
    """
    return [
        AbilitySpec("static", [EffectSpec("flash_permission", {"type_filter": ["sorcery", "dragon"]})]),
    ]


register("Whirlwing Stormbrood", _whirlwing_stormbrood)
register("Whirlwing Stormbrood // Dynamic Soar", _whirlwing_stormbrood)

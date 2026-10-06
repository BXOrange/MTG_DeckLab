from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "creature card with mana value 4 or less".
_MAX_MANA_VALUE = 4


def _phoenix_down() -> list[AbilitySpec]:
    """{1}{W}, {T}, Exile this artifact: Choose one —
    • Return target creature card with mana value 4 or less from your graveyard to the battlefield tapped.
    • Exile target Skeleton, Spirit, or Zombie.

    — PLAY-ALL (Revival Trance). A modal activated ability (Umezawa's Jitte's shape) whose cost carries ``exile_self``.
    Mode 1 is `return_from_graveyard` (tapped, ``max_mana_value`` 4); mode 2 is an `exile` of a creature narrowed by a
    ``subtype_any`` filter.
    """
    return [
        AbilitySpec(
            "activated",
            [],
            cost={"text": "{1}{w}, {t}", "exile_self": True},
            modes={
                "choose": 1,
                "options": [
                    [EffectSpec("return_from_graveyard", {
                        "target_kind": "graveyard_creature", "destination": "battlefield", "tapped": True,
                        "max_mana_value": _MAX_MANA_VALUE,
                    })],
                    [EffectSpec("exile", {
                        "target_kind": "creature",
                        "creature_filter": {"subtype_any": ["skeleton", "spirit", "zombie"]},
                    })],
                ],
                "descriptions": [
                    "Bringe eine Kreaturenkarte mit Manawert 4 oder weniger aus deinem Friedhof getappt ins Spiel zurück.",
                    "Verbanne ein Skelett, einen Geist oder einen Zombie.",
                ],
            },
        ),
    ]


register("Phoenix Down", _phoenix_down)

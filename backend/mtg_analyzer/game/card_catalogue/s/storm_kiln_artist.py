from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _storm_kiln_artist() -> list[AbilitySpec]:
    """This creature gets +1/+0 for each artifact you control.
    Magecraft — Whenever you cast or copy an instant or sorcery spell,
    create a Treasure token.

    — Imodane deck batch. Magecraft already parses on its own —
    reproduced verbatim. The P/T clause is `anthem`'s existing
    ``power_count``, self-scoped, with the existing
    `artifacts_you_control` selector.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "self", "power": 1, "power_count": "artifacts_you_control"})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Treasure"})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_card_types": ["instant", "sorcery"],
            },
        ),
    ]


register("Storm-Kiln Artist", _storm_kiln_artist)

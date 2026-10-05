from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hermit_druid() -> list[AbilitySpec]:
    """{G}, {T}: Reveal cards from the top of your library until you
    reveal a basic land card. Put that card into your hand and all other
    cards revealed this way into your graveyard.

    — MEC-43. `dig_until`'s existing dig with the new ``rest_destination=
    "graveyard"`` value (`RulesEngine._graveyard_remaining`, the graveyard
    sibling of the existing library-bottom/shuffled destinations) — the
    hit destination stays the default ``"hand"``.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("dig_until", {
                "criteria": {"basic": True}, "hit_destination": "hand",
                "rest_destination": "graveyard",
            })],
            cost={"text": "{G}, {T}"},
        ),
    ]


register("Hermit Druid", _hermit_druid)

from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _archivist_of_oghma() -> list[AbilitySpec]:
    """Flash. Whenever an opponent searches their library, you gain 1 life
    and draw a card.

    — Archivist of Oghma. Flash is a keyword, already covered by the
    parser's keyword catalogue. `RulesEngine._request_search` already fires
    ``EventType.LIBRARY_SEARCHED`` (``player_id``-keyed) for every search,
    real or fizzled (no eligible cards) — this batch added it to
    `effect_binder._GROUP_CONTROLLER_EVENT_KEYS` so the existing "group" +
    ``controller: "not_you"`` trigger-subject scope (built for Seedborn
    Muse) applies here too.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_life", {"amount": 1}), EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.LIBRARY_SEARCHED,
                "condition": {"subject": "group", "controller": "not_you"},
            },
        )
    ]


register("Archivist of Oghma", _archivist_of_oghma)

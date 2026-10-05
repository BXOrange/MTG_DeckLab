from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kishla_skimmer() -> list[AbilitySpec]:
    """Flying
    Whenever a card leaves your graveyard during your turn, draw a card. This ability triggers only once each turn.

    — PLAY-ALL Step 2 (Sultai Arisen). Flying is a keyword fold-in. The trigger is the parser's graveyard-exit shape
    (`CARDS_LEFT_GRAVEYARD`, ``graveyard_owner: you``, ``during_your_turn``) with the RULE 603.2 once-per-turn limit
    (``limit``, PAR-14), so a mass exit and several separate exits in one turn all draw exactly once.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.CARDS_LEFT_GRAVEYARD, "graveyard_owner": "you",
                "during_your_turn": True, "limit": True,
            },
        ),
    ]


register("Kishla Skimmer", _kishla_skimmer)

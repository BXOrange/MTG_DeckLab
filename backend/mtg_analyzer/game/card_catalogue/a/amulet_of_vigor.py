from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _amulet_of_vigor() -> list[AbilitySpec]:
    """Whenever a permanent you control enters tapped, untap it.

    — PLAY-ALL Step 2 (Kodama). The parser's own "whenever a permanent you
    control enters, untap it" (ENTERS_BATTLEFIELD, group ``controller: you``,
    ``type: permanent``, a `tap` ``untap`` on ``trigger_subject``) with the
    "enters tapped" half expressed as the group filter ``tapped: True``: the
    enters-tapped replacement (RULE 614.1) has already set the flag when the
    event fires, so an untapped entrant never matches.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("tap", {
                "target_kind": "trigger_subject", "untap": True, "trigger_event_key": "__group_subject__",
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {
                    "subject": "group", "controller": "you", "other": False, "type": "permanent",
                    "filter": {"tapped": True},
                },
            },
        ),
    ]


register("Amulet of Vigor", _amulet_of_vigor)

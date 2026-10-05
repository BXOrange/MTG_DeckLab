from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "two additional +1/+1 counters".
_ADDITIONAL_COUNTERS = 2


def _curator_beastie() -> list[AbilitySpec]:
    """Reach
    Colorless creatures you control enter with two additional +1/+1 counters on them.
    Whenever this creature enters or attacks, manifest dread. (Look at the top two cards of your library. Put one onto the battlefield face down as a 2/2 creature and the other into your graveyard. Turn it face up any time for its mana cost if it's a creature card.)

    — PLAY-ALL (Jump Scare!). Reach is a keyword; the manifest-dread trigger is the parser's. The counters are the
    `extra_etb_counter` static filtered to ``colorless`` — a face-down manifest is a colourless 2/2, so it enters
    with two counters (Beastie itself, being green, never does).
    """
    return [
        AbilitySpec("static", [EffectSpec("extra_etb_counter", {
            "kind": "+1/+1", "count": _ADDITIONAL_COUNTERS, "filter": {"colorless": True}, "other": False,
        })]),
        AbilitySpec(
            "triggered",
            [EffectSpec("manifest_dread", {})],
            trigger={"event": [EventType.ENTERS_BATTLEFIELD, EventType.ATTACKS], "condition": {"subject": "self"}},
        ),
    ]


register("Curator Beastie", _curator_beastie)

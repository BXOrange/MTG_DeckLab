from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _morcants_loyalist() -> list[AbilitySpec]:
    """Other Elves you control get +1/+1.
    When this creature dies, return another target Elf card from your
    graveyard to your hand.

    — Eliferate deck batch. The anthem already parses; the dies trigger
    reuses `ReturnFromGraveyardEffect`'s new `subtype` filter
    (`targeting.TargetSpec.subtype`) scoped to "elf", which also excludes
    this card's own now-in-the-graveyard copy the same way an ordinary
    battlefield "another" target excludes its own source.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_creature", "subtype": "elf",
                "destination": "hand",
            })],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
        ),
    ]


register("Morcant's Loyalist", _morcants_loyalist)

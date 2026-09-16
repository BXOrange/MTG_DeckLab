from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _leonin_relic_warder() -> list[AbilitySpec]:
    """When this creature enters, you may exile target artifact or
    enchantment. When this creature leaves the battlefield, return the
    exiled card to the battlefield under its owner's control.

    — Leonin Relic-Warder. A new O-Ring-shaped linkage primitive this
    batch: `ExileEffect(remember=True)` stamps the exiled card's own
    ``instance_id`` onto this creature's `GameObject.linked_exile_id`
    (survives however long it stays exiled, arbitrarily many turns);
    `ReturnLinkedExileEffect`, on this creature's own leaves-battlefield
    trigger, reads it back and returns that exact card, clearing the link.
    ``target_kind="permanent"`` (broader than "artifact or enchantment" —
    no target kind unions two card types) is the same documented
    `_TARGET_ROWS` simplification several other catalogue entries use.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {
                "target_kind": "permanent", "optional": True, "remember": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_linked_exile", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Leonin Relic-Warder", _leonin_relic_warder)

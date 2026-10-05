from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _voracious_bibliophile() -> list[AbilitySpec]:
    """Flying, vigilance
    Whenever you cast a spell with one or more targets, draw that many
    cards.

    — Voracious Bibliophile. Flying and vigilance come from the RULE 702
    keyword catalogue. The trigger is the cast head (`SPELL_CAST`, "you")
    with the new ``spell_targets_at_least`` floor on the event's
    ``target_count`` (RULE 115.1, every chosen target, players included);
    "that many" is a `bind` over that same event field.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("bind", {
                "name": "n",
                "amount": {"kind": "trigger_event", "field": "target_count"},
                "effects": [{"type": "draw", "params": {"count": "$n"}}],
            })],
            trigger={
                "event": EventType.SPELL_CAST, "condition": {"subject": "you"},
                "spell_targets_at_least": 1,
            },
        ),
    ]


register("Voracious Bibliophile", _voracious_bibliophile)

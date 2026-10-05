from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mazemind_tome() -> list[AbilitySpec]:
    """{T}, Put a page counter on this artifact: Scry 1.
    {2}, {T}, Put a page counter on this artifact: Draw a card.
    When there are four or more page counters on this artifact, exile it. If you do, you gain 4 life.

    — Keen Engineering deck batch. The two activations are the parser's own claims. The state trigger
    (RULE 603.8) is Nine Lives' shape: counters only arrive through the two costs, so a self `COUNTER`
    trigger gated by `source_counters_at_least` is rules-equivalent. "If you do" is the exile
    succeeding, and the Tome only leaves from here, so the life gain follows it unconditionally.
    """
    return [
        AbilitySpec(
            "activated", [EffectSpec("scry", {"count": 1})],
            cost={"text": "{t}, put a page counter on ~"},
            raw_text="{t}, put a page counter on ~: scry 1.",
        ),
        AbilitySpec(
            "activated", [EffectSpec("draw", {"count": 1})],
            cost={"text": "{2}, {t}, put a page counter on ~"},
            raw_text="{2}, {t}, put a page counter on ~: draw a card.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {"target_kind": None}), EffectSpec("gain_life", {"amount": 4})],
            trigger={
                "event": EventType.COUNTER, "filter": {"kind": "page"}, "condition": {"subject": "self"},
                "source_counters_at_least": {"count": 4, "kind": "page"},
            },
        ),
    ]


register("Mazemind Tome", _mazemind_tome)

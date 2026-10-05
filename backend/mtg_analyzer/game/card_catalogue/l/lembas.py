from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lembas() -> list[AbilitySpec]:
    """When this artifact enters, scry 1, then draw a card.
    {2}, {T}, Sacrifice this artifact: You gain 3 life.
    When this artifact is put into a graveyard from the battlefield, its
    owner shuffles it into their library.

    Simplified: the dies-trigger self-shuffle isn't modeled (no "return
    self from graveyard" primitive exists for `ReturnFromGraveyardEffect`,
    only a real RULE 115 target pick) — Lembas simply stays in the
    graveyard once it dies, same as an ordinary permanent.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("scry", {"count": 1}), EffectSpec("draw", {"count": 1})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("gain_life", {"amount": 3})],
            cost={"mana": "{2}", "taps_self": True, "sacrifice": "self"},
        ),
    ]


register("Lembas", _lembas)

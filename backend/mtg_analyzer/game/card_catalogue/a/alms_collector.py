from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _alms_collector() -> list[AbilitySpec]:
    """Flash
    If an opponent would draw two or more cards, instead you and that
    player each draw a card.

    — MEC-32. Flash is the ordinary keyword fold-in. The draw-replacement
    clause needed a genuinely new primitive: no per-card `DRAW` event can
    see "the whole attempted instruction was for 2+ cards" (each card in a
    multi-draw is independently replaceable per RULE 120.3), so
    `RulesEngine.draw` was restructured to fire one `EventType.DRAW_
    INSTRUCTION` event for the whole call before splitting into per-card
    `DRAW` events — see that event's own docstring and `effects.
    _split_multi_draw_replacement`.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("split_multi_draw", {"min_count": 2})],
        ),
    ]


register("Alms Collector", _alms_collector)

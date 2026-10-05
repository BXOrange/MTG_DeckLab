from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _soul_guide_lantern() -> list[AbilitySpec]:
    """When this artifact enters, exile target card from a graveyard.
    {T}, Sacrifice this artifact: Exile each opponent's graveyard.
    {1}, {T}, Sacrifice this artifact: Draw a card.

    — PLAY-ALL Step 2 (Counter Intelligence). The ETB exile and the draw ability
    are the parser's own claims, reproduced. The middle one is
    `exile_all_graveyards` with the new ``opponents_only`` flag
    (`exile_control.ExileAllGraveyardsEffect`) — every other player's graveyard,
    never the controller's own.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {"target_kind": "any_graveyard_card"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("exile_all_graveyards", {"opponents_only": True})],
            cost={"text": "{T}, Sacrifice ~"},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1})],
            cost={"text": "{1}, {T}, Sacrifice ~"},
        ),
    ]


register("Soul-Guide Lantern", _soul_guide_lantern)

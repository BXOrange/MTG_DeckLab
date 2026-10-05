from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dockside_extortionist() -> list[AbilitySpec]:
    """When this creature enters, create X Treasure tokens, where X is the
    number of artifacts and enchantments your opponents control.

    — Dockside Extortionist. A new opponents-scoped `continuous.
    count_selector` entry this batch (``artifacts_and_or_enchantments_
    opponents_control``, the mirror image of the existing "you control"
    one) plus a new `CreateTokenEffect.count_selector` param reading it
    live at resolution.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "token_name": "Treasure",
                "count_selector": "artifacts_and_or_enchantments_opponents_control",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        )
    ]


register("Dockside Extortionist", _dockside_extortionist)

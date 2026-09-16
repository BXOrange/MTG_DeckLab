from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _yarok_the_desecrated() -> list[AbilitySpec]:
    return [AbilitySpec(
        "static", [EffectSpec("trigger_doubler", {"cause_filter": [EventType.ENTERS_BATTLEFIELD]})],
    )]


register("Yarok, the Desecrated", _yarok_the_desecrated)

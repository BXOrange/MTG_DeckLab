from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rest_in_peace() -> list[AbilitySpec]:
    """When this enchantment enters, exile all graveyards.
    If a card or token would be put into a graveyard from anywhere, exile
    it instead.

    — MEC-43. The ETB is the already-shipped `ExileAllGraveyardsEffect`
    (Farewell's own mass-exile mode); the static is `graveyard_redirect`
    with ``scope="any"`` (unscoped, unlike Leyline of the Void's
    opponent-only reading).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_all_graveyards", {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("graveyard_redirect", {"scope": "any"})],
        ),
    ]


register("Rest in Peace", _rest_in_peace)

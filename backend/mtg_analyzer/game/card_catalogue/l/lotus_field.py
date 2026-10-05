from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Quandrix Unlimited singletons (+ Emeria, a Lorehold land)
# ===========================================================================


def _lotus_field() -> list[AbilitySpec]:
    """Hexproof
    This land enters tapped.
    When this land enters, sacrifice two lands.
    {T}: Add three mana of any one color.

    Hexproof / enters-tapped / the mana ability all come from the ordinary
    keyword + land pipelines; only the ETB self-sacrifice needs authoring."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice", {"what": "land", "count": 2})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Lotus Field", _lotus_field)

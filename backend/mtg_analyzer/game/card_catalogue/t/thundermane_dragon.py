from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _thundermane_dragon() -> list[AbilitySpec]:
    """Flying
    You may look at the top card of your library any time.
    You may cast creature spells with power 4 or greater from the top of your library. If you cast a
    creature spell this way, it gains haste until end of turn.

    — Reign of Dragons deck batch. Flying is a keyword; the look permission is the parser's own claim.
    The cast permission is a second `top_library_permission` limited to creature spells whose printed
    power is 4 or more (``spell_criteria``). The haste is a cast trigger on a creature spell cast from
    the library (`spell_cast_from`) granting haste to that spell. **Documented simplification:** it
    keys on the cast zone, so a creature cast from the top by *another* effect while Thundermane is
    out also gains haste.
    """
    return [
        AbilitySpec("static", [EffectSpec("top_library_permission", {"look": True})]),
        AbilitySpec("static", [EffectSpec("top_library_permission", {
            "cast_spells": True, "creature_only": True, "spell_criteria": {"min_power": 4},
        })]),
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_keyword_to_trigger_subject", {"keyword": "haste"})],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"},
                     "spell_filter": {"card_type": "creature"}, "spell_cast_from": ["library"]},
        ),
    ]


register("Thundermane Dragon", _thundermane_dragon)

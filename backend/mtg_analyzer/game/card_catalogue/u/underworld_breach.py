from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _underworld_breach() -> list[AbilitySpec]:
    """Each nonland card in your graveyard has escape. The escape cost is
    equal to the card's mana cost plus exile three other cards from your
    graveyard.
    At the beginning of the end step, sacrifice this enchantment.

    — Underworld Breach. A **granted** Escape (RULE 702.138), which is a
    different thing from the printed keyword the engine already supported:
    it applies to cards in a *graveyard*, so no battlefield selector and no
    printed-keyword scan could ever reach them, and its cost has to be
    assembled per-card (each card's own mana cost plus the exile clause)
    rather than read from a fixed printed string.

    Modeled as a ``grant_escape`` static consulted by `GameEngine.
    _graveyard_cast_keyword`/`_escape_cost` (`continuous.
    granted_escape_for`), which is why the rest of the escape machinery —
    the zone gate, the alternative cost, `_pay_escape_graveyard_cost` —
    needed no changes at all. Kept out of `recompute` proper for the same
    reason the other permission statics are: nothing about the affected
    card's *characteristics* changes, so there is no layer to write it into.

    The self-sacrifice is the shipped `sacrifice_self` effect on an end-step
    trigger.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_escape", {
                "nonland_only": True,
                "exile_from_graveyard": 3,
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_self", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}},
        ),
    ]


register("Underworld Breach", _underworld_breach)

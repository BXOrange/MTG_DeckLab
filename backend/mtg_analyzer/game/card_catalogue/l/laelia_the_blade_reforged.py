from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Laelia, the Blade Reforged (exile-from-library/graveyard
# counter trigger) — PAR-60
# ===========================================================================
# Attack trigger reuses `impulsive_draw` (same_turn_only). The counter
# trigger is a new binder key ``exiled_from_your_library_or_graveyard`` on
# `EventType.EXILE` (which now carries ``from_zone``). Haste folds in from
# the RULE 702 keyword catalogue.


def _laelia_the_blade_reforged() -> list[AbilitySpec]:
    """Haste
    Whenever Laelia attacks, exile the top card of your library. You may
    play that card this turn.
    Whenever one or more cards are put into exile from your library and/or
    your graveyard, put a +1/+1 counter on Laelia."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("impulsive_draw", {"count": 1, "same_turn_only": True})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"})],
            trigger={
                "event": EventType.EXILE,
                "exiled_from_your_library_or_graveyard": True,
            },
        ),
    ]


register("Laelia, the Blade Reforged", _laelia_the_blade_reforged)

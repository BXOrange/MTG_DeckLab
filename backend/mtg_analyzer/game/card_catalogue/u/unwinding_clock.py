from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _unwinding_clock() -> list[AbilitySpec]:
    """Untap all artifacts you control during each other player's untap step.

    — PLAY-ALL (Shorikai Vehicles). Victory Chimes' `untap_each_untap_step` (`continuous.untaps_in_every_untap_step`, consulted by the untap step
    for the permanents of the players whose step it is *not*), scoped to every artifact you control.
    """
    return [AbilitySpec("static", [EffectSpec("untap_each_untap_step", {"affects": "artifacts_you_control"})])]


register("Unwinding Clock", _unwinding_clock)

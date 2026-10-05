from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _earthshape() -> list[AbilitySpec]:
    """Earthshape (Instant, {2}{W})

    "Earthbend 3. Then each creature you control with power less than or
    equal to that land's power gains hexproof and indestructible until end
    of turn. You gain hexproof until end of turn."

    — PAR-30, the last card of the Earthbend residue cluster. Hand-authored
    rather than parsed: the "power <= that land's power" threshold is a
    read of the just-earthbent land's power that no general handler
    warrants building for one Avatar-set singleton.

    Two documented simplifications:
    - **"that land's power" is modeled as the literal earthbend amount
      (3).** RULE 701.66's earthbend makes the target land a 0/0 that then
      gets N +1/+1 counters, i.e. exactly N/N, so "that land's power" is 3
      absent any other P/T modifier on that land — the common case.
      `PumpEffect.creature_filter` (which now also narrows the
      ``selector``-group branch, not just the targeted one) carries the
      ``max_power`` bound; `combat.matches_object_filter` is the same
      predicate `TargetSpec.creature_filter` uses everywhere else. The
      animated land itself is a 3/3 creature you control and so is
      (correctly) among the protected creatures.
    - **"You gain hexproof until end of turn" is dropped.** Player-level
      hexproof is a deliberately-unmodeled concept in this engine (same
      call as Veil of Summer's player-level hexproof in the Kinnan/M-K
      batch) — a whole targeting-legality subsystem for one rider.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("earthbend", {"amount": 3}),
                EffectSpec("pump", {
                    "selector": "creatures_you_control",
                    "creature_filter": {"max_power": 3},
                    "keywords": ["hexproof", "indestructible"],
                }),
            ],
        )
    ]


register("Earthshape", _earthshape)

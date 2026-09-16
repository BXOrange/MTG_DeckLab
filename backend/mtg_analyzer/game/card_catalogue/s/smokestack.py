from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _smokestack() -> list[AbilitySpec]:
    """At the beginning of your upkeep, you may put a soot counter on this
    artifact.
    At the beginning of each player's upkeep, that player sacrifices a
    permanent of their choice for each soot counter on this artifact.

    — MEC-43 round 4E. The first ability is a plain optional self-counter
    add (RULE 122.1), same shape countless other upkeep triggers already
    use. The second reuses Tangle Wire's own "read the count live off the
    source's own counters, offer N picks via the general chooser" shape
    (`TapPermanentsPerCounterEffect`) — its new sibling,
    `SacrificePermanentsPerCounterEffect`, swaps ``action="tap"`` for
    ``"sacrifice"`` and drops Tangle Wire's own artifact/creature/land +
    untapped-only filter (Smokestack taxes *any* permanent).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"kind": "soot", "amount": 1})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
            optional=True,
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_permanents_per_counter", {"kind": "soot"})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}},
        ),
    ]


register("Smokestack", _smokestack)

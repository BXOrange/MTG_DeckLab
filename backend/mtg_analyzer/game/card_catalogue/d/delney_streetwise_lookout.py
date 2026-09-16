from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _delney_streetwise_lookout() -> list[AbilitySpec]:
    """Creatures you control with power 2 or less can't be blocked by
    creatures with power 3 or greater.
    If a triggered ability of a creature you control with power 2 or less
    triggers, that ability triggers an additional time.

    — MEC-43 round 2. The first clause is the already-shipped qualified
    combat-restriction shape (Challenger Troll/Flopsie's own group
    ``min_power``/``max_power`` scoping, here on the *restricted* side
    instead), just with a blocker-power filter instead of a group-scope
    P/T qualifier. The second reuses `TriggerDoublerEffect`'s new
    ``max_power`` axis — unscoped by "another" (the printed clause names
    none, unlike Roaming Throne's), so Delney's own future triggers would
    double themselves too, though this card prints no other trigger of
    its own for that to matter today.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("combat_restriction", {
                "affects": "creatures_you_control", "max_power": 2,
                "kind": "cant_be_blocked_by", "filter": {"min_power": 3},
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("trigger_doubler", {"max_power": 2})],
        ),
    ]


register("Delney, Streetwise Lookout", _delney_streetwise_lookout)

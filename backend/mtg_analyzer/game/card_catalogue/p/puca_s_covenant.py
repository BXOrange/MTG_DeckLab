from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _pucas_covenant() -> list[AbilitySpec]:
    """Whenever a creature you control with a counter on it dies, you may
    return another target permanent card with mana value less than or equal
    to the number of counters on that creature from your graveyard to your
    hand. Do this only once each turn.

    Authored: a DIES trigger over the C3a "creature you control with a
    counter on it" group subject, with ``limit`` (RULE 603.2 "…only once
    each turn"). The return targets a `graveyard_permanent` with the new
    dynamic `max_mana_value="trigger_dying_counters"` bound — resolved in
    `targeting.legal_targets` from the DIES event's snapshotted counter
    total (RULE 400.7). "another" (RULE 109.5, excluding the just-died
    creature itself) is a minor accepted precision loss, in line with this
    file's RULE 115 norms.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_permanent", "destination": "hand",
                "optional": True, "max_mana_value": "trigger_dying_counters",
            })],
            trigger={
                "event": "DIES",
                "condition": {"subject": "group", "type": "creature",
                              "controller": "you", "has_counter": True, "other": False},
                "limit": True,
            },
        )
    ]


register("Puca's Covenant", _pucas_covenant)

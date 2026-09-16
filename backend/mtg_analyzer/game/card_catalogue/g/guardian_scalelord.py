from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Lorehold spirits: graveyard-reanimate-by-dynamic-mv + phasing
# ===========================================================================
# Engine: `targeting.legal_targets` gained ``max_mana_value`` sentinels
# ``source_power`` and ``trigger_damage_amount``.


def _guardian_scalelord() -> list[AbilitySpec]:
    """Backup 1
    Flying
    Whenever this creature attacks, return target nonland permanent card with
    mana value X or less from your graveyard to the battlefield, where X is
    this creature's power."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_nonland_permanent", "destination": "battlefield",
                "max_mana_value": "source_power",
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Guardian Scalelord", _guardian_scalelord)

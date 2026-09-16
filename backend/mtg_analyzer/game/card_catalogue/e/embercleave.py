from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _embercleave() -> list[AbilitySpec]:
    """Flash
    This spell costs {1} less to cast for each attacking creature you control.
    When Embercleave enters, attach it to target creature you control.
    Equipped creature gets +1/+1 and has double strike and trample.
    Equip {3}

    — Embercleave. Flash comes from the RULE 702 keyword catalogue (and is
    honoured for casting timing, `GameEngine.can_cast`). The attacker-count
    cost reduction (MEC-6) is `cost_reduction` with `affects="self"` and
    `per="attacking_creatures_you_control"` — the same self-scoped discount
    shape Delve/Affinity already exercise via `continuous.
    self_cost_reduction_for`, read live at cast time (`GameObject.attacking`,
    RULE 508.1) so a cast after declare attackers sees the real count.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {"affects": "self", "generic": 1,
                                            "per": "attacking_creatures_you_control"})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("attach", {"target_kind": "creature_you_control"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 1, "toughness": 1}),
                EffectSpec("grant_keyword", {"affects": "attached_permanent",
                                              "keywords": ["double_strike", "trample"]}),
            ],
        ),
    ]


register("Embercleave", _embercleave)

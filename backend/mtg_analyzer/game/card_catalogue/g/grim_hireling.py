from __future__ import annotations

from ....models.game.events import EventType
from ...costs import SACRIFICE_COUNT_X
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _grim_hireling() -> list[AbilitySpec]:
    """Whenever one or more creatures you control deal combat damage to a
    player, create two Treasure tokens.
    {B}, Sacrifice X Treasures: Target creature gets -X/-X until end of
    turn. Activate only as a sorcery.

    — MEC-43 round 4A. The trigger is already fully `MODELED` by the
    oracle-text parser (MEC-29's aggregate
    ``EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER``) — reused as-is,
    not re-derived. Only the activated ability needs hand-authoring:
    "Sacrifice X Treasures" is `costs.ActivationCost.sacrifice_count`'s
    ``(count, subtype)`` shape, widened by this same ticket with a new
    `costs.SACRIFICE_COUNT_X` sentinel — the `REMOVE_COUNTERS_X` sibling
    for a sacrifice-cost component whose count is RULE 601.2b's announced
    ``x`` rather than a printed number. The stack item's own ``x``
    (`GameEngine.activate_ability`'s ``x`` param, stamped onto
    ``source.x_paid``) then reaches "gets -X/-X" through the existing
    ``"-x"`` sentinel `RulesEngine._substitute_x` already rewrites on
    `PumpEffect.power`/``toughness`` for any spell/ability — no new
    effect-side code.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 2, "token_name": "Treasure"})],
            trigger={
                "event": EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER,
                "condition": {"subject": "you"},
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {
                "power": "-x", "toughness": "-x", "target_kind": "creature",
            })],
            cost={"text": "{B}", "sacrifice_count": (SACRIFICE_COUNT_X, "treasure"),
                  "sorcery_speed_only": True},
        ),
    ]


register("Grim Hireling", _grim_hireling)

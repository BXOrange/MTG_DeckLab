from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _professor_hojo() -> list[AbilitySpec]:
    """The first activated ability you activate during your turn that targets a creature you control costs {2} less to activate.
    Whenever one or more creatures you control become the target of an activated ability, draw a card. This ability triggers only once each turn.

    — PLAY-ALL (Limit Break). The discount is `cost_reduction` with ``scope="activation"`` and the new ``first_targeting_own_creature`` (`continuous.activation_cost_reduction_for`: the ability's
    cost carries ``targets_own_creature``, stamped at bind time, and no earlier ACTIVATED_ABILITY event of yours this turn did), gated on your turn. The draw is a `BECOMES_TARGET` trigger (the
    new ``target_creature_you_control`` filter key) with the action-once-per-turn marker. **Simplifications:** "creature you control" is read off the ability's target kinds (``…_you_control``), and
    any ability (a triggered one too, which shares ``item_kind: "ability"``) counts for the draw.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "scope": "activation", "generic": 2, "first_targeting_own_creature": True, "active_if": {"kind": "your_turn"},
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1}), EffectSpec("action_once_per_turn_marker", {})],
            trigger={
                "event": EventType.BECOMES_TARGET,
                "filter": {"item_kind": "ability", "target_creature_you_control": True},
            },
        ),
    ]


register("Professor Hojo", _professor_hojo)

from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _chain_of_vapor() -> list[AbilitySpec]:
    """Return target nonland permanent to its owner's hand. Then that
    permanent's controller may sacrifice a land of their choice. If the
    player does, they may copy this spell and may choose a new target for
    that copy.

    — Vivi B4 batch. `return_to_hand` for the bounce; `PayCostThenEffect`'s
    general "you may pay `<cost>`. If you do, nothing further." (RULE
    118.3) models the land sacrifice itself with a new
    ``payer="previous_target_controller"`` (`GameContext.previous_targets`
    — it's the *bounced permanent's* controller being asked, almost always
    an opponent, not this spell's own caster). **Documented
    simplification**: "they may copy this spell and may choose a new
    target for that copy" is dropped rather than approximated —
    `CopySpellEffect.copy_self` ("copy this spell" while it's still
    resolving) can't reach back through a `pending_choice` pause (by the
    time the player answers "pay", the original has already finished
    resolving and left the stack for the graveyard, RULE 608.2m), and a
    same-target "copy" would fizzle for real play anyway: the only target
    this MVP can default to is the permanent the first sentence just
    bounced, which is no longer a legal "target nonland permanent" once
    it's sitting in hand — RAW's own "you may choose new targets" is
    exactly there to route around that, and this engine doesn't offer that
    choice yet. Sacrificing the land is still a real, correctly-costed
    decision on its own.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("return_to_hand", {"target_kind": "nonland_permanent"}),
                EffectSpec("pay_cost_then", {
                    "cost": "sacrifice a land",
                    "payer": "previous_target_controller",
                    "effects": [],
                }),
            ],
        ),
    ]


register("Chain of Vapor", _chain_of_vapor)

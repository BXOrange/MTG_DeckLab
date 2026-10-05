from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _torch_the_tower() -> list[AbilitySpec]:
    """Bargain
    Torch the Tower deals 2 damage to target creature or planeswalker. If
    this spell was bargained, instead it deals 3 damage to that permanent
    and you scry 1.
    If a permanent dealt damage by Torch the Tower would die this turn,
    exile it instead.

    — Imodane deck batch. Bargain is auto-bound. **Documented
    simplification**: the bargained "and you scry 1" rider isn't modeled
    alongside the amount override (`amount_if_bargained` swaps the number;
    composing it with a *second*, conditional-only-when-bargained effect
    would need `EffectSpec.condition`'s `bargained` key on a *second*
    `scry` effect — omitted here, so a bargained cast deals 3 damage
    without the scry). The die-to-exile clause is the new
    `grant_die_to_exile_this_turn`, unconditional (it applies whichever
    amount was dealt).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("damage", {
                    "amount": 2, "target_kind": "creature_or_planeswalker", "amount_if_bargained": 3,
                }),
                EffectSpec("grant_die_to_exile_this_turn", {"target_kind": None}),
            ],
        ),
    ]


register("Torch the Tower", _torch_the_tower)

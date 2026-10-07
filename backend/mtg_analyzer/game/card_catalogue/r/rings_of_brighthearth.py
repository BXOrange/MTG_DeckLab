from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rings_of_brighthearth() -> list[AbilitySpec]:
    """Whenever you activate an ability, if it isn't a mana ability, you may
    pay {2}. If you do, copy that ability. You may choose new targets for
    the copy.

    — Rings of Brighthearth, MEC-43 round 4G. `EventType.ACTIVATED_ABILITY`
    already fires for every non-mana activated ability (RULE 605.1a mana
    abilities never use the stack, so "isn't a mana ability" needs no
    separate check — the same fact `Flamescroll Celebrant`/`Runic Armasaur`
    already document), and `pay_cost_then` (RULE 118.3) already handles the
    optional {2}. The genuinely new part is copying an ability that's
    already on the stack (RULE 707.10): `CopyAbilityEffect`/`RulesEngine.
    copy_ability` are the ability-item siblings of the existing spell-copy
    machinery (`CopySpellEffect`/`copy_spell`), identifying "that ability"
    by `StackItem.stack_id` (ENG-26) instead of a `GameObject.instance_id`
    — remembered onto `GameObject.remembered_stack_id` by
    `remember_trigger_stack_id=True` at the ability's first, still-live
    `apply()`, since the "if you do" branch only runs once the pay-or-not
    choice is answered, by which point `context.trigger_event` has closed.

    The copied ability offers optional new targets after payment,
    before entering the stack, while retaining its original source.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{2}",
                "effects": [{"type": "copy_ability", "params": {}}],
                "remember_trigger_stack_id": True,
            })],
            trigger={
                "event": EventType.ACTIVATED_ABILITY,
                "condition": {"subject": "group", "controller": "you"},
            },
        )
    ]


register("Rings of Brighthearth", _rings_of_brighthearth)

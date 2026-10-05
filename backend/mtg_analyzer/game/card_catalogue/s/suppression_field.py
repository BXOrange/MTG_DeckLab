from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _suppression_field() -> list[AbilitySpec]:
    """Activated abilities cost {2} more to activate unless they're mana
    abilities.

    — MEC-12 (cEDH staples 2). `activation_cost_reduction_for` previously
    only ever supported a *reduction*, scoped to one of three named
    selectors (attached/subtype/card_type) — this needed all three widened
    at once: a signed net that can tax as well as discount
    (`GameEngine._reduced_activation_mana`'s new `increase_generic` branch,
    mirroring `CastingMixin._adjust_cost`'s existing spell-side handling), a
    genuinely unscoped ``affects="all_permanents"`` selector, and
    `activation_prohibition`'s own ``except_mana_abilities``/
    ``is_mana_ability`` rider threaded through the whole activation-cost
    call chain (`_can_pay_activation_cost`/`_pay_activation_cost`/
    `tap_for_mana`) so a mana ability is actually exempt rather than taxed
    twice over (once here, and it would have been wrong either way).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "scope": "activation", "affects": "all_permanents",
                "generic": 2, "increase": True, "except_mana_abilities": True,
            })],
        ),
    ]


register("Suppression Field", _suppression_field)

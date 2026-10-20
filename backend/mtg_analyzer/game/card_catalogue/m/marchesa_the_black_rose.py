from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _marchesa_the_black_rose() -> list[AbilitySpec]:
    """Dethrone (Whenever this creature attacks the player with the most
    life or tied for most life, put a +1/+1 counter on it.)
    Other creatures you control have dethrone.
    Whenever a creature you control with a +1/+1 counter on it dies,
    return that card to the battlefield under your control at the
    beginning of the next end step.

    — Marchesa, the Black Rose. Her own printed Dethrone needs no
    hand-authoring — it's a plain Scryfall keyword flag `combat.has` already
    recognizes (`RulesEngine.check_dethrone`, called from `GameEngine.
    declare_attackers` since Dethrone's amount is fixed per-firing rather
    than bind-on-load, the same "per-firing dynamic" reason `check_rampage`
    isn't a bind-time `TriggeredAbility` either). The "Other creatures you
    control have dethrone" static *is* hand-authored here, below, as an
    ordinary layer-6 `grant_keyword` — `check_dethrone` reads `combat.has`
    fresh at attack-declaration time, so a creature holding the granted
    keyword dethrones exactly like one with it printed. The third clause
    (the RULE 603.7 delayed-return trigger) is an ordinary group DIES
    trigger over `delay_return_dying_subject` — a good showcase card for the "planned"
    delayed-trigger UI panel, same reason Ephemerate/Sneak Attack/Meek
    Attack were picked.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "other_creatures_you_control", "keywords": ["dethrone"],
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("delay_return_dying_subject", {
                "tapped": False, "under_your_control": True, "step": "end", "scope": "any",
            })],
            trigger={"event": "DIES", "condition": {
                "subject": "group", "controller": "you", "other": False,
                "type": "creature", "has_counter_kind": "+1/+1",
            }},
        )
    ]


register("Marchesa, the Black Rose", _marchesa_the_black_rose)

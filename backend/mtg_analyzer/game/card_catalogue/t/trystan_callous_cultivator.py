from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _trystan_callous_cultivator() -> list[AbilitySpec]:
    """Deathtouch
    Whenever this creature enters or transforms into Trystan, Callous
    Cultivator, mill three cards. Then if there is an Elf card in your
    graveyard, you gain 2 life.
    At the beginning of your first main phase, you may pay {B}. If you do,
    transform Trystan.

    — Eliferate deck batch. Deathtouch is a RULE 702 keyword, auto-bound.
    **Documented simplification**: the "or transforms into ~" half of the
    first trigger isn't modeled — this engine has no `TRANSFORMED` event
    at all yet (a genuinely open engine-primitive gap, not specific to
    this card), so only the ETB half fires; the mill+conditional-lifegain
    body itself is fully modeled (`mill` + `EffectSpec.condition`'s new
    `graveyard_has_type`). The second ability is a plain resolve-time
    `pay_cost_then` (RULE 118.3) wrapping `transform`.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("mill", {"count": 3}),
                EffectSpec("gain_life", {"amount": 2}, condition={"graveyard_has_type": "elf"}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{B}",
                "effects": [{"type": "transform", "params": {}}],
            })],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "main1"},
                "phase_relation": "you",
            },
        ),
    ]


register("Trystan, Callous Cultivator", _trystan_callous_cultivator)
register("Trystan, Callous Cultivator // Trystan, Penitent Culler", _trystan_callous_cultivator)

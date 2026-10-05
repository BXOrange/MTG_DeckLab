from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sigardas_aid() -> list[AbilitySpec]:
    """You may cast Aura and Equipment spells as though they had flash.
    Whenever an Equipment you control enters, you may attach it to target
    creature you control.

    — Sigarda's Aid. Only the second ability is modeled. RULE 603.3d's "it"
    is the Equipment that just entered — not the ability's own source
    (Sigarda's Aid itself), and not a choice — which is exactly ENG-13's
    general per-firing dynamic reference: `AttachTriggeringPermanentEffect`
    reads it off `GameContext.trigger_event`'s own ``instance_id``, the
    same field `ReturnSharedTypePermanentEffect` reads for Cloudstone
    Curio's "it". Only the destination ("target creature you control") is a
    real choice, and it's what makes the whole ability optional — declining
    the target is declining the attach, matching `CreateTokenMayAttach
    EquipmentEffect`'s own "target_spec.optional" idiom rather than a
    separate `AbilitySpec.optional` flag.

    The first ability — a *standing* cast-as-flash permission scoped to two
    card types — isn't modeled: it needs a static permission distinct from
    the existing `grant_flash_until_eot` (a one-shot "this turn" grant,
    Borne Upon a Wind-shaped), a documented gap unrelated to ENG-13.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("attach_triggering_permanent", {
                "target_kind": "creature_you_control", "optional": True,
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {
                    "subject": "group", "type": "artifact",
                    "subtypes": ["equipment"], "controller": "you",
                },
            },
        )
    ]


register("Sigarda's Aid", _sigardas_aid)

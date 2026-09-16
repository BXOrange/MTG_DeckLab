from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _chain_lightning() -> list[AbilitySpec]:
    """Chain Lightning deals 3 damage to any target. Then that player or
    that permanent's controller may pay {R}{R}. If the player does, they
    may copy this spell and may choose a new target for that copy.

    — Imodane deck batch. **Documented simplification**: the "hot potato"
    copy-chain (control of the copy passes to whichever player just paid,
    who may then trigger *another* copy) isn't modeled — no primitive
    threads a spell copy's "controller" through a resolve-time optional
    payment offered to the *damage recipient* rather than the caster, and
    building one is disproportionate to this one card. Modeled as the
    bare "deals 3 damage to any target."
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {"amount": 3, "target_kind": "any"})],
        ),
    ]


register("Chain Lightning", _chain_lightning)

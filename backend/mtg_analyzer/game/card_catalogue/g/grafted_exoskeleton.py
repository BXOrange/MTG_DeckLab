from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _grafted_exoskeleton() -> list[AbilitySpec]:
    """Equipped creature gets +2/+2 and has infect.
    Whenever this Equipment becomes unattached from a permanent,
    sacrifice that permanent.
    Equip {2}

    — Imodane deck batch. The anthem+infect grant and Equip already
    parse on their own — reproduced verbatim. **Documented
    simplification**: "whenever ~ becomes unattached" isn't modeled —
    this engine has no `attached_to` change event at all yet (every
    detach site — RULE 704.5m/n's illegal-attachment cleanup, a manual
    re-equip — mutates `GameObject.attached_to` directly with no
    broadcast), a genuinely open engine-primitive gap beyond this one
    card, so building it here is disproportionate.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 2, "toughness": 2}),
                EffectSpec("grant_keyword", {"affects": "attached_permanent", "keywords": ["infect"]}),
            ],
        ),
    ]


register("Grafted Exoskeleton", _grafted_exoskeleton)

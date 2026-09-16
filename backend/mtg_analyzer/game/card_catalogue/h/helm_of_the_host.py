from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _helm_of_the_host() -> list[AbilitySpec]:
    """At the beginning of combat on your turn, create a token that's a
    copy of equipped creature, except the token isn't legendary. That
    token gains haste.
    Equip {5}

    — Equip is synthesized by the keyword catalogue; the triggered ability
    itself needed no new primitive at all (MEC-12). `CopyPermanentEffect`
    already supports ``target_kind="attached_permanent"`` (Mirrormind
    Crown's own "copies of equipped creature"), ``not_legendary``
    (Multiversal Recruitment-shaped), and ``haste`` (Kiki-Jiki, Mirror
    Breaker-shaped) — Helm of the Host is simply the first card combining
    exactly these three already-shipped params on one effect.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("copy_permanent", {
                "target_kind": "attached_permanent", "not_legendary": True, "haste": True,
            })],
            trigger={
                "event": "STEP_BEGIN",
                "filter": {"step": "begin_combat"},
                "phase_relation": "you",
            },
        ),
    ]


register("Helm of the Host", _helm_of_the_host)

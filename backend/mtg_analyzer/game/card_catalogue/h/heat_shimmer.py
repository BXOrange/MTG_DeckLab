from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _heat_shimmer() -> list[AbilitySpec]:
    """Create a token that's a copy of target creature, except it has
    haste and "At the beginning of the end step, exile this token."

    — The single-target sibling of Twinflame's own delayed-exile shape
    (MEC-12, this same batch): rather than literally granting a quoted
    triggered ability onto the freshly-made token (a real but heavier
    mechanism this engine already avoids for exactly this template — see
    Kiki-Jiki/Puppeteer Clique's own "create/reanimate with haste,
    [sacrifice/exile] it at the beginning of the next end step" primitive
    in `Done_Backend.md`'s Marchesa V4.2 entry), the caster-side
    `create_delayed_trigger`/`exile_specific` pair reaches the identical
    board outcome — the token is gone at the next end step regardless of
    which player controls it. Target is any creature (not "you control"),
    unlike Twinflame — `CopyPermanentEffect`'s plain ``"creature"``
    ``target_kind`` default already matches.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("copy_permanent", {"target_kind": "creature", "haste": True}),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "capture": "created_objects",
                    "effects": [{"type": "exile_specific", "params": {}}],
                }),
            ],
        ),
    ]


register("Heat Shimmer", _heat_shimmer)

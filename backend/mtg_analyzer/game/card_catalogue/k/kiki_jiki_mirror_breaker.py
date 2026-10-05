from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kiki_jiki_mirror_breaker() -> list[AbilitySpec]:
    """Haste
    {T}: Create a token that's a copy of target nonlegendary creature you
    control, except it has haste. Sacrifice it at the beginning of the
    next end step.

    — Kiki-Jiki, Mirror Breaker. Haste is a keyword, already covered by
    the parser's keyword catalogue. The activated ability needed a hand
    spec for its "except it has haste" + "sacrifice it at the beginning
    of the next end step" pair — `effects.CopyPermanentEffect`'s new
    ``haste`` param (grants the copy temp haste directly, rather than a
    second untargeted keyword-grant effect that couldn't tell *which*
    creature just got made), then `create_delayed_trigger`'s new
    ``capture="created_objects"`` to arm a RULE 603.7 delayed
    ``sacrifice_specific`` naming that exact token (`GameContext.
    created_objects`, the same "the tokens…" referent Fabricate/Martial
    Coup already read) — this batch's general primitive for the whole
    "create/return X, it gains haste, [sacrifice/exile] it at the
    beginning of the next end step" template family (~40 real cards
    total between this shape and Puppeteer Clique's reanimate-and-exile
    sibling), not a one-off for this card alone.

    Documented simplification: the real printed restriction is "target
    **nonlegendary** creature you control" — this engine's targeting
    vocabulary has no "nonlegendary" creature kind yet (only the positive
    "legendary permanent"), so it's modeled as a plain "creature you
    control" target; illegally copying a legendary creature just runs
    into the ordinary RULE 704.5j legend-rule SBA like any other route to
    a second legendary permanent, rather than being refused as an illegal
    target the way real Kiki-Jiki refuses it outright.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("copy_permanent", {
                    "target_kind": "creature_you_control", "count": 1, "haste": True,
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "end",
                    "scope": "any",
                    "capture": "created_objects",
                    "effects": [{"type": "sacrifice_specific", "params": {}}],
                    "description": "Kiki-Jiki: Kopie opfern",
                }),
            ],
            cost={"taps_self": True},
        ),
    ]


register("Kiki-Jiki, Mirror Breaker", _kiki_jiki_mirror_breaker)

from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mizzixs_mastery() -> list[AbilitySpec]:
    """Mizzix's Mastery (Sorcery, {3}{R})

    "Exile target card that's an instant or sorcery from your graveyard.
    For each card exiled this way, copy it, and you may cast the copy
    without paying its mana cost. Exile Mizzix's Mastery.
    Overload {5}{R}{R}{R} (You may cast this spell for its overload cost.
    If you do, change "target" in its text to "each.")"

    Modeled as a direct free-cast window on the exiled card itself
    (`ExileEffect`'s new ``grant_free_cast_window`` param, MEC-43 round
    4C, reusing `RulesEngine.grant_free_cast_window_from_exile` exactly
    as `ExileTopFromEachPlayerCastFreeEffect`/`ReboundFreeCastWindowEffect`
    already do) rather than literally instantiating a second "copy"
    object — nothing this engine tracks distinguishes an uncast copy from
    the real exiled card, and RULE 707.10a means an uncast copy simply
    ceases to exist either way if it isn't cast, so the two are
    behaviourally identical. The trailing self-exile is `ExileEffect`'s
    plain, untargeted self form (``target_kind=None`` — Mnemonic Betrayal-
    shaped).

    **Documented simplification**: Overload (RULE 702.96) isn't bound to
    real behaviour yet — the same posture `Selfless Safewright`'s and
    `City on Fire`'s own catalogue entries already take, which note it
    "come[s] from the RULE 702 keyword catalogue automatically" with no
    real "target"→"each" mode swap. Building that (a genuinely different,
    untargeted effect body reached via an alternative cost) is out of
    scope for this single card's own coverage gate.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("exile", {
                    "target_kind": "graveyard_instant_or_sorcery",
                    "grant_free_cast_window": True,
                }),
                EffectSpec("exile", {"target_kind": None}),
            ],
        ),
        AbilitySpec(
            "keyword", [], keyword={"name": "overload", "cost": "{5}{R}{R}{R}"},
        ),
    ]


register("Mizzix's Mastery", _mizzixs_mastery)

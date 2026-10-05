from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _the_mycosynth_gardens() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {1}, {T}: Add one mana of any color.
    {X}, {T}: This land becomes a copy of target nontoken artifact you control
    with mana value X.

    — PLAY-ALL Step 2 (Counter Intelligence). The two mana abilities are read
    off the land's own text (the mana-ability layer, as for any land). The
    third is `become_copy_permanent` (Shameless Charlatan's non-reverting
    copy, RULE 707.2 — the printed text has no duration) with two new target
    pieces: ``exact_mana_value: "x"`` (the announced X, the same sentinel
    Mizzix's-style X targets use) and the `nontoken_artifact_you_control`
    kind. No ``keep_own_abilities``: a plain copy erases the land's abilities,
    exactly as printed.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("become_copy_permanent", {
                "target_kind": "nontoken_artifact_you_control", "exact_mana_value": "x",
            })],
            cost={"text": "{X}, {T}"},
        ),
    ]


register("The Mycosynth Gardens", _the_mycosynth_gardens)

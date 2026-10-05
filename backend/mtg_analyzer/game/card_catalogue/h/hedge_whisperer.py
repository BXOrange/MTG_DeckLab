from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hedge_whisperer() -> list[AbilitySpec]:
    """You may choose not to untap this creature during your untap step.
    {3}{G}, {T}, Collect evidence 4: Target land you control becomes a 5/5
    green Plant Boar creature with haste for as long as this creature
    remains tapped. It's still a land. Activate only as a sorcery.

    — Collect Evidence activated-body residue (sub-cluster b). The animate
    body is a targeted `grant_until` on `land_you_control`: a layer-4
    `type_change` (Plant Boar 5/5, `add_types` keeps the land type — "it's
    still a land") plus a layer-6 `grant_keyword` haste, both on the one
    picked land via the new `extra_statics` list. The "for as long as ~
    remains tapped" bound is `condition={"kind": "source_tapped"}` (RULE
    611.2b — the effect *ends*, doesn't merely pause, when Hedge Whisperer
    untaps). ``sorcery_speed_only`` carries "Activate only as a sorcery".
    The keep-tapped static is the general `no_untap_optional`.
    """
    return [
        AbilitySpec("static", [EffectSpec("no_untap_optional", {})]),
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "duration": "end_of_turn",  # overridden to for_as_long_as by `condition`
                "target_kind": "land_you_control",
                "condition": {"kind": "source_tapped"},
                # Documented simplification: "green" isn't modeled —
                # `type_change`'s layer-4 params have no colour field (same
                # call as Restless Cottage). The animated land keeps
                # whatever colour identity it already had.
                "static": {
                    "type": "type_change",
                    "params": {
                        "add_types": ["creature"],
                        "add_subtypes": ["Plant", "Boar"],
                        "power": 5, "toughness": 5,
                    },
                },
                "extra_statics": [
                    {"type": "grant_keyword", "params": {"keywords": ["haste"]}},
                ],
            })],
            cost={"text": "{3}{G}, {T}, Collect evidence 4", "sorcery_speed_only": True},
        ),
    ]


register("Hedge Whisperer", _hedge_whisperer)

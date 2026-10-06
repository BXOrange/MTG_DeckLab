from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: Tiered mode costs (RULE 702.183), in printed order: Cure, Cura, Curaga.
_TIER_COSTS = ["{0}", "{1}", "{3}{W}"]


def _protect_effect(**params) -> EffectSpec:
    """"Gains hexproof and indestructible until end of turn" — a one-turn keyword grant on a target permanent, or
    (``lock_group``) on the permanents the controller has as it resolves (RULE 611.2c)."""
    return EffectSpec("grant_until", {
        "static": {"type": "grant_keyword", "params": {
            "keywords": ["hexproof", "indestructible"], **({"affects": params.pop("affects")} if "affects" in params else {}),
        }},
        "duration": "end_of_turn", **params,
    })


def _restoration_magic() -> list[AbilitySpec]:
    """Tiered (Choose one additional cost.)
    • Cure — {0} — Target permanent gains hexproof and indestructible until end of turn.
    • Cura — {1} — Target permanent gains hexproof and indestructible until end of turn. You gain 3 life.
    • Curaga — {3}{W} — Permanents you control gain hexproof and indestructible until end of turn. You gain 6 life.

    — PLAY-ALL (Hope to the last). Tiered (RULE 702.183) is a Spree-shaped modal spell with exactly one mode chosen:
    ``modes["mode_costs"]`` prices each mode and `GameEngine._modal_extra_cost` now also prices a single chosen mode. The
    bodies are `grant_until` keyword grants (targeted, or ``lock_group`` over ``permanents_you_control``) plus `gain_life`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "choose": 1, "tiered": True,
                "mode_costs": list(_TIER_COSTS),
                "options": [
                    [_protect_effect(target_kind="permanent")],
                    [_protect_effect(target_kind="permanent"), EffectSpec("gain_life", {"amount": 3})],
                    [
                        _protect_effect(target_kind=None, lock_group=True, affects="permanents_you_control"),
                        EffectSpec("gain_life", {"amount": 6}),
                    ],
                ],
                "descriptions": [
                    "Cure: Ein Permanent erhält Fluchsicherheit und Unzerstörbarkeit bis zum Ende des Zuges.",
                    "Cura: Ein Permanent erhält Fluchsicherheit und Unzerstörbarkeit bis zum Ende des Zuges. Du erhältst 3 Lebenspunkte.",
                    "Curaga: Deine Permanents erhalten Fluchsicherheit und Unzerstörbarkeit bis zum Ende des Zuges. Du erhältst 6 Lebenspunkte.",
                ],
            },
        ),
    ]


register("Restoration Magic", _restoration_magic)

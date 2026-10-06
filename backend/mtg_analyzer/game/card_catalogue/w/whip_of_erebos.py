from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _whip_of_erebos() -> list[AbilitySpec]:
    """Creatures you control have lifelink.
    {2}{B}{B}, {T}: Return target creature card from your graveyard to the battlefield. It gains haste. Exile it at the beginning of the next end step. If it would leave the battlefield, exile it instead of putting it anywhere else. Activate only as a sorcery.

    — PLAY-ALL (Death Toll). The lifelink static is the parser's. The activation is what the parser claims for the same text without the
    last sentence (Unearth's shape: `return_from_graveyard`, a haste grant, the end-step `create_delayed_trigger` exile, `sorcery_speed_marker`)
    plus `exile_instead_of_leaving` for "if it would leave the battlefield, exile it instead of putting it anywhere else" (From the Catacombs).
    """
    return [
        AbilitySpec("static", [EffectSpec("grant_keyword", {"affects": "creatures_you_control", "keywords": ["lifelink"]})]),
        AbilitySpec(
            "activated",
            [
                EffectSpec("return_from_graveyard", {"target_kind": "graveyard_creature", "destination": "battlefield"}),
                EffectSpec("grant_until", {
                    "static": {"type": "grant_keyword", "params": {"keywords": ["haste"]}},
                    "duration": "rest_of_game", "previous_subject": True, "target_kind": None,
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "scope": "any", "capture": "previous_or_self",
                    "effects": [{"type": "exile_specific", "params": {}}],
                }),
                EffectSpec("exile_instead_of_leaving", {}),
                EffectSpec("sorcery_speed_marker", {}),
            ],
            cost={"text": "{2}{b}{b}, {t}"},
        ),
    ]


register("Whip of Erebos", _whip_of_erebos)

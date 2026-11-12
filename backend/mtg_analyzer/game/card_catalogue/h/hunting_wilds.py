from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hunting_wilds() -> list[AbilitySpec]:
    """Kicker {3}{G} (You may pay an additional {3}{G} as you cast this spell.)
    Search your library for up to two Forest cards, put them onto the battlefield tapped, then shuffle.
    If this spell was kicked, untap all Forests put onto the battlefield this way. They become 3/3 green creatures with haste that are still lands.
    """
    return [AbilitySpec("spell_effect", [EffectSpec("search", {
        "criteria": {"type": "forest"}, "count": 2, "destination": "battlefield_tapped",
        "then_specs": [{"type": "for_each", "condition": {"kind": "kicked", "min": 1}, "params": {
            "over": {"previous_targets": True}, "effects": [
                {"type": "tap", "params": {"target_kind": "permanent", "untap": True}},
                {"type": "grant_until", "params": {
                    "duration": "rest_of_game", "target_kind": "permanent",
                    "static": {"type": "type_change", "params": {
                        "affects": "self", "add_types": ["creature"], "power": 3, "toughness": 3}},
                    "extra_statics": [{"type": "color_change", "params": {"affects": "self", "colors": ["G"]}},
                                      {"type": "grant_keyword", "params": {"affects": "self", "keywords": ["haste"]}}],
                }},
            ],
        }}],
    })])]


register("Hunting Wilds", _hunting_wilds)

"""Sea Troll."""
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sea_troll():
    """{U}: Regenerate this creature. Activate only if this creature blocked or was blocked by a blue creature this turn."""
    return [AbilitySpec("activated", [EffectSpec("regenerate", {"target_kind": None})], cost={
        "mana": "{U}", "activation_condition": {
            "kind": "source_blocked_or_was_blocked_by_color_this_turn", "color": "U",
        },
    })]


register("Sea Troll", _sea_troll)

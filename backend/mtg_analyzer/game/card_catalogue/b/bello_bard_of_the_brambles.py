from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _bello_bard_of_the_brambles() -> list[AbilitySpec]:
    """During your turn, each non-Equipment artifact and non-Aura enchantment you control with mana
    value 4 or greater is a 4/4 Elemental creature in addition to its other types and has
    indestructible, haste, and "Whenever this creature deals combat damage to a player, draw a card."

    — Animated Army deck batch. One structured group selector (the Cyberdrive Awakener ``affects``
    shape) picks the permanents: a mana-value-4-or-more filter ANDed with an ``any_of`` of the two
    type/exclusion pairs, and every static carries ``active_if: your_turn``. Three statics share it:
    a layer-4 ``type_change`` (creature + Elemental, 4/4), a layer-6 ``grant_keyword`` and the
    parser's own ``grant_triggered_ability`` shape for the combat-damage draw.
    """
    scope = {
        "zone": "battlefield", "of": "you",
        "filter": {
            "min_mana_value": 4,
            "any_of": [
                {"card_type": "artifact", "without_subtype": "Equipment"},
                {"card_type": "enchantment", "without_subtype": "Aura"},
            ],
        },
    }
    on_turn = {"kind": "your_turn"}
    return [
        AbilitySpec("static", [EffectSpec("type_change", {
            "affects": dict(scope), "add_types": ["creature"], "add_subtypes": ["Elemental"],
            "power": 4, "toughness": 4, "active_if": dict(on_turn),
        })]),
        AbilitySpec("static", [EffectSpec("grant_keyword", {
            "affects": dict(scope), "keywords": ["indestructible", "haste"], "active_if": dict(on_turn),
        })]),
        AbilitySpec("static", [EffectSpec("grant_triggered_ability", {
            "affects": dict(scope), "trigger_event": "DAMAGE", "optional": False,
            "filter": {"combat": True, "is_player": True},
            "grant_effects": [{"type": "draw", "params": {"count": 1}}], "active_if": dict(on_turn),
        })]),
    ]


register("Bello, Bard of the Brambles", _bello_bard_of_the_brambles)

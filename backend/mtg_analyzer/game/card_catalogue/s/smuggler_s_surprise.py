
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _smuggler_s_surprise() -> list[AbilitySpec]:
    'Spree (Choose one or more additional costs.)\n+ {2} — Mill four cards. You may put up to two creature and/or land cards from among the milled cards into your hand.\n+ {4}{G} — You may put up to two creature cards from your hand onto the battlefield.\n+ {1} — Creatures you control with power 4 or greater gain hexproof and indestructible until end of turn.'
    return [
        AbilitySpec("spell_effect", [], modes={
            "choose": 1, "at_least": True, "mode_costs": ["{2}", "{4}{G}", "{1}"],
            "options": [
                [EffectSpec("mill", {"count": 4}), EffectSpec("choose_objects", {
                    "pool_zone": "milled", "card_types_any": ["creature", "land"], "what": "card",
                    "count": 2, "optional": True, "action": "return_from_graveyard_to_hand",
                })],
                [EffectSpec("put_from_hand_onto_battlefield", {"criteria": {"type": "creature"}, "count": 2})],
                [EffectSpec("pump", {"selector": "creatures_you_control", "creature_filter": {"min_power": 4}, "keywords": ["hexproof", "indestructible"]})],
            ],
            "descriptions": ["Mill four, recover up to two creature or land cards.", "Put up to two creature cards from your hand onto the battlefield.", "Creatures with power 4 or greater gain hexproof and indestructible."],
        }),
    ]


register("Smuggler's Surprise", _smuggler_s_surprise)

from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _luxior_and_shadowspear() -> list[AbilitySpec]:
    """Equipped creature gets +1/+1 for each counter on it, and has trample and lifelink.
    {1}: Permanents your opponents control lose hexproof and indestructible until end of turn.
    Equipped permanent isn't a planeswalker and is a creature in addition to its other types.
    Equip creature or planeswalker {3}

    PAR-109. See `luxior_giada_s_gift` for the counter bonus and the type change. "Equip creature or planeswalker {3}" is
    the keyword's Equip {3} for creatures (declared below, since Scryfall lists no Equip keyword for this wording) plus
    a second hand-authored attach at the same cost for planeswalkers. The {1} ability is what the parser already claims for Shadowspear.
    """
    return [
        # Scryfall lists no Equip keyword for the "creature or planeswalker" wording, so the creature Equip is declared.
        AbilitySpec("keyword", [], keyword={"name": "equip", "cost": "{3}"}),
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {
                    "affects": "attached_permanent", "power": 1, "toughness": 1,
                    "power_count": "total_counters_on_affected", "toughness_count": "total_counters_on_affected",
                }),
                EffectSpec("grant_keyword", {"affects": "attached_permanent", "keywords": ["trample", "lifelink"]}),
            ],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {
                "removed_keywords": ["hexproof", "indestructible"],
                "selector": {"zone": "battlefield", "of": "opponents"},
            })],
            cost={"text": "{1}"},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("type_change", {
                "affects": "attached_permanent", "add_types": ["creature"], "remove_types": ["planeswalker"],
            })],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("attach", {
                "target_kind": "targetable_creature_or_planeswalker_you_control", "allow_planeswalker": True,
            })],
            cost={"text": "{3}", "sorcery_speed_only": True, "attach_kind": "equip"},
        ),
    ]


register("Luxior and Shadowspear", _luxior_and_shadowspear)

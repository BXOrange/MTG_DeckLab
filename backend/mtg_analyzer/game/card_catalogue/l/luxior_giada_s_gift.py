from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _luxior_giada_s_gift() -> list[AbilitySpec]:
    """Equipped creature gets +1/+1 for each counter on it.
    Equipped permanent isn't a planeswalker and is a creature in addition to its other types. (Loyalty abilities can
    still be activated.)
    Equip planeswalker {1}
    Equip {3}

    PAR-109. The bonus is the parser's `anthem` over `total_counters_on_affected` (every counter on the equipped
    permanent, loyalty counters included: a 4-loyalty planeswalker is a 4/4). The type clause is a layer-4
    `type_change` on the attached permanent (RULE 613.1d: adds creature, removes planeswalker); a planeswalker has no
    printed P/T, so it is 0/0 before the bonus (the card's ruling), and `GameObject.is_planeswalker` follows the layer
    while the printed type keeps its loyalty abilities usable (RULE 606). "Equip {3}" is the keyword's own ability;
    "Equip planeswalker {1}" is a second, hand-authored attach whose host is a planeswalker you control
    (`AttachEffect.allow_planeswalker`): it is no creature until the Equipment makes it one, and stays a legal host
    afterwards because Luxior's own static keeps it a creature (RULE 704.5n re-check).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "attached_permanent", "power": 1, "toughness": 1,
                "power_count": "total_counters_on_affected", "toughness_count": "total_counters_on_affected",
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("type_change", {
                "affects": "attached_permanent", "add_types": ["creature"], "remove_types": ["planeswalker"],
            })],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("attach", {"target_kind": "planeswalker_you_control", "allow_planeswalker": True})],
            cost={"text": "{1}", "sorcery_speed_only": True, "attach_kind": "equip"},
        ),
    ]


register("Luxior, Giada's Gift", _luxior_giada_s_gift)

from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "for each creature you control" (RULE 613.4c) -- the same structured count for both stats.
_CREATURES_YOU_CONTROL = {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature"}}

#: Equip {4}, minus this much while the Equipment's controller is the monarch.
_MONARCH_EQUIP_DISCOUNT = 3


def _crown_of_gondor() -> list[AbilitySpec]:
    """Equipped creature gets +1/+1 for each creature you control.
    When a legendary creature you control enters, if there is no monarch, you become the monarch.
    Equip {4}. This ability costs {3} less to activate if you're the monarch.

    The anthem is Sword of the Squeak's attached-permanent anthem with a creature count. The trigger is
    Tamiyo's `become_monarch` behind a RULE 603.4 intervening-if (``trigger["active_if"]``, the new
    `no_monarch` static condition, RULE 726.1). The equip discount is the equip-scoped self-only
    `cost_reduction` (Plate Armor's shape) gated on the existing `is_monarch` condition.
    """
    return [
        AbilitySpec("static", [EffectSpec("anthem", {
            "affects": "attached_permanent", "power": 1, "toughness": 1,
            "power_count": dict(_CREATURES_YOU_CONTROL), "toughness_count": dict(_CREATURES_YOU_CONTROL),
        })]),
        AbilitySpec(
            "triggered",
            [EffectSpec("become_monarch", {})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "controller": "you",
                              "filter": {"card_type": "creature", "legendary": True}},
                "active_if": {"kind": "no_monarch"},
            },
        ),
        AbilitySpec("keyword", [], keyword={"name": "equip", "cost": "{4}"}),
        AbilitySpec("static", [EffectSpec("cost_reduction", {
            "scope": "activation", "attach_kind": "equip", "self_only": True,
            "generic": _MONARCH_EQUIP_DISCOUNT, "active_if": {"kind": "is_monarch"},
        })]),
    ]


register("Crown of Gondor", _crown_of_gondor)

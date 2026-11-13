
from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _portal_mage() -> list[AbilitySpec]:
    "Flash\nWhen this creature enters during the declare attackers step, you may reselect which player or permanent target attacking creature is attacking. (It can't attack its controller or their permanents.)"
    return [
        AbilitySpec("triggered", [EffectSpec("reselect_attack", {}, condition={"kind": "during_step", "step": "declare_attackers"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"},
                     "active_if": {"kind": "during_step", "step": "declare_attackers"}}),
    ]


register('Portal Mage', _portal_mage)

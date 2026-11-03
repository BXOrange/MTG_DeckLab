from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ravenous_gigantotherium() -> list[AbilitySpec]:
    """Devour 3 (As this creature enters, you may sacrifice any number of creatures. It enters with three times that many +1/+1 counters on it.)
When this creature enters, it deals X damage divided as you choose among up to X target creatures, where X is its power. Each of those creatures deals damage equal to its power to this creature."""
    return [
        AbilitySpec("enter_replacement", [EffectSpec("entry_effect", {"effects": [
            {"type": "devour_entry", "params": {"multiplier": 3}},
        ]})]),
        AbilitySpec("triggered", [EffectSpec("divided_damage_then_retaliate", {})],
                    trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}}),
    ]


register("Ravenous Gigantotherium", _ravenous_gigantotherium)

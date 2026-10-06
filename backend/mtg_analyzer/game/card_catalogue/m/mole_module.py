from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mole_module() -> list[AbilitySpec]:
    """Mill four, then optionally put a permanent among those exact cards onto the battlefield."""
    return [AbilitySpec("triggered", [EffectSpec("mill_recover_permanent", {"count": 4, "destination": "battlefield"})],
        trigger={"event": "DAMAGE", "condition": {"subject": "self"}, "filter": {"combat": True, "is_player": True}})]


register('Mole Module', _mole_module)

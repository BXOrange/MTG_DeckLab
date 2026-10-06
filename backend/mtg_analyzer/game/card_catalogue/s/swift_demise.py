from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _swift_demise() -> list[AbilitySpec]:
    """Deal one, then destroy opposing creatures damaged this turn, including ones whose damage was removed."""
    return [AbilitySpec("spell_effect", [
        EffectSpec("damage", {"amount": 1, "target_kind": "creature"}),
        EffectSpec("destroy", {"group": {"zone": "battlefield", "of": "opponents", "filter": {"card_type": "creature", "damaged_this_turn": True}}}),
    ])]


register('Swift Demise', _swift_demise)

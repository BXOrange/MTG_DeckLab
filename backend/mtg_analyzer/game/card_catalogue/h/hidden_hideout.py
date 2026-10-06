from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hidden_hideout() -> list[AbilitySpec]:
    """The land mana ability and tapped entry are oracle-derived; the counter-gated lifelink ability targets."""
    return [AbilitySpec("activated", [EffectSpec("pump", {
        "target_kind": "creature_you_control", "keywords": ["lifelink"], "creature_filter": {"has_counter": True},
    })], cost={"text": "{2}, {T}"})]


register('Hidden Hideout', _hidden_hideout)

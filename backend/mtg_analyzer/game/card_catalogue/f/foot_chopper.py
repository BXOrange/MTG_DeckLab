from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _foot_chopper() -> list[AbilitySpec]:
    """Ninja creation/attachment and flying; an optional sacrifice draws the sacrificed host's last-known power."""
    return [
        AbilitySpec("triggered", [
            EffectSpec("create_token", {"count": 1, "token_name": "Ninja", "power": 1, "toughness": 1,
                "colors": ["B"], "subtypes": ["Ninja"]}),
            EffectSpec("attach", {"target_kind": "created"}),
        ], trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}}),
        AbilitySpec("static", [EffectSpec("grant_keyword", {"affects": "attached_permanent", "keywords": ["flying"]})]),
        AbilitySpec("triggered", [EffectSpec("sacrifice_attached_draw_power", {})],
            trigger={"event": "DAMAGE", "condition": {"subject": "attached_permanent"},
                     "filter": {"combat": True, "is_player": True}}),
    ]


register('Foot Chopper', _foot_chopper)

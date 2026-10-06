from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _cid_freeflier_pilot() -> list[AbilitySpec]:
    """Equipment and Vehicle spells you cast cost {1} less to cast.
    Jump — During your turn, Cid has flying.
    {2}, {T}: Return target Equipment or Vehicle card from your graveyard to your hand.

    — PLAY-ALL (Limit Break). Jump is the parser's claim (a self flying grant gated on your turn). The discount is `cost_reduction` with a ``spell_subtype`` list (OR) of
    Equipment and Vehicle. The activation is `return_from_graveyard` over the new ``graveyard_equipment_or_vehicle`` kind.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {"generic": 1, "spell_subtype": ["equipment", "vehicle"]})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"affects": "self", "keywords": ["flying"], "active_if": {"kind": "your_turn"}})],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("return_from_graveyard", {"target_kind": "graveyard_equipment_or_vehicle", "destination": "hand"})],
            cost={"text": "{2}, {t}"},
        ),
    ]


register("Cid, Freeflier Pilot", _cid_freeflier_pilot)

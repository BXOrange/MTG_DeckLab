from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _adeline_resplendent_cathar() -> list[AbilitySpec]:
    """Vigilance
    Adeline's power is equal to the number of creatures you control.
    Whenever you attack, for each opponent, create a 1/1 white Human creature token that's tapped and attacking that player or a planeswalker they control.

    — Adeline. Vigilance comes from the keyword catalogue; the power is the parser's own `pt_cda`. "Whenever
    you attack" is `ATTACKERS_DECLARED` (one per declaration, so attacking two opponents triggers once, unlike
    the per-defender `PLAYER_ATTACKED`); the body is `create_token` with ``per_opponent`` (RULE 508.4a — each
    token attacks a distinct opponent) and ``defender_planeswalker`` (its controller may instead pick a planeswalker
    that opponent controls, `RulesEngine._offer_attack_defenders`).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("pt_cda", {"affects": "self", "power_count": {
                "zone": "battlefield", "of": "you", "filter": {"card_type": "creature"},
            }})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1, "colors": ["W"], "subtypes": ["Human"],
                "token_name": "Human", "per_opponent": True, "tapped": True, "attacking": True,
                "defender_planeswalker": True,
            })],
            trigger={
                "event": EventType.ATTACKERS_DECLARED, "condition": {"subject": "you"},
                "attackers_declared": {"filter": {"card_type": "creature"}, "min": 1},
            },
        ),
    ]


register("Adeline, Resplendent Cathar", _adeline_resplendent_cathar)

from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _digsite_engineer() -> list[AbilitySpec]:
    """Whenever you cast an artifact spell, you may pay {2}. If you do, create a 0/0 colorless Construct artifact creature token with "This token gets +1/+1 for each artifact you control."

    — PLAY-ALL (Shorikai Vehicles). The cast head and the optional {2} payment are the parser's (`pay_cost_then`); the token is Urza's Saga's
    Construct (``grant_self_anthem`` scaling with the artifacts you control).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {"cost": "{2}", "effects": [{"type": "create_token", "params": {
                "count": 1, "power": 0, "toughness": 0, "colors": [], "subtypes": ["Construct"], "token_name": "Construct",
                "is_artifact": True,
                "grant_self_anthem": {"power": 1, "toughness": 1, "power_count": "artifacts_you_control",
                                      "toughness_count": "artifacts_you_control"},
            }}]})],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"}, "spell_filter": {"card_type": "artifact"}},
        ),
    ]


register("Digsite Engineer", _digsite_engineer)

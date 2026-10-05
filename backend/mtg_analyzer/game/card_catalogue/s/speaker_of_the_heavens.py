from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "at least 7 life more than your starting life total".
_LIFE_OVER_STARTING = 7


def _speaker_of_the_heavens() -> list[AbilitySpec]:
    """Vigilance, lifelink (Attacking doesn't cause this creature to tap. Damage dealt by this creature also causes you to gain that much life.)
    {T}: Create a 4/4 white Angel creature token with flying. Activate only if you have at least 7 life more than your starting life total and only as a sorcery.

    — PLAY-ALL (Calling All Angels). Keywords are the catalogue's. The ability is a token `create_token` whose cost carries
    ``sorcery_speed_only`` plus an ``activation_condition`` on `life_over_starting_at_least`.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "count": 1, "power": 4, "toughness": 4, "colors": ["W"], "subtypes": ["Angel"], "keywords": ["flying"],
                "token_name": "Angel",
            })],
            cost={"text": "{T}", "sorcery_speed_only": True, "activation_condition": {
                "kind": "life_over_starting_at_least", "amount": _LIFE_OVER_STARTING,
            }},
        ),
    ]


register("Speaker of the Heavens", _speaker_of_the_heavens)

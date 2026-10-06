from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "four other artifact creatures and/or Vehicles" — the printed count.
_OTHERS_EXILED = 4
#: A `sacrifice_count`-style permanent word: other permanents that are artifact creatures or Vehicles ("_or_" splits, "_" ANDs).
_OTHER_ARTIFACT_CREATURE_OR_VEHICLE = "other_artifact_creature_or_vehicle"


def _mechtitan_core() -> list[AbilitySpec]:
    """{5}, Exile this Vehicle and four other artifact creatures and/or Vehicles you control: Create Mechtitan, a legendary 10/10 Construct artifact creature token with flying, vigilance, trample, lifelink, and haste that's all colors. When that token leaves the battlefield, return all cards exiled with this Vehicle except this card to the battlefield tapped under their owners' control.
    Crew 2

    — PLAY-ALL (Shorikai Vehicles). Crew is the keyword. The cost is the new `ActivationCost.exile_others` (four *other* artifact creatures/Vehicles you
    control, picked like `sacrifice_count`'s pool, recorded in `exiled_with_ids`) plus `exile_self`. The effect creates the Mechtitan token and hands it
    the exiled-with list (`transfer_exiled_with_to_created`); the token's own leaves-the-battlefield trigger is the hand-authored "Mechtitan" entry, which
    runs `return_all_exiled_with` tapped.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("create_token", {
                    "count": 1, "power": 10, "toughness": 10, "colors": ["W", "U", "B", "R", "G"], "subtypes": ["Construct"],
                    "keywords": ["flying", "vigilance", "trample", "lifelink", "haste"], "token_name": "Mechtitan",
                    "legendary": True, "is_artifact": True,
                }),
                EffectSpec("transfer_exiled_with_to_created", {}),
            ],
            cost={"mana": "{5}", "exile_self": True, "exile_others": [_OTHERS_EXILED, _OTHER_ARTIFACT_CREATURE_OR_VEHICLE]},
        ),
    ]


register("Mechtitan Core", _mechtitan_core)

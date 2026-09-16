from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _guardian_sunmare() -> list[AbilitySpec]:
    """Guardian Sunmare (Creature — Horse Mount, {3}{W}{W})

    "Ward {2}
    Whenever this creature attacks while saddled, search your library for
    a nonland permanent card with mana value 3 or less, put it onto the
    battlefield, then shuffle.
    Saddle 4"

    Ward and Saddle are both already parser-claimable keywords — Saddle's
    own cost/state (`ActivationCost.saddle_power`, `GameObject.saddled_
    until_turn`, `effects.BecomeSaddledEffect`) is new real behaviour
    (MEC-40; previously keyword-recognized only, per RULE 702.171). The
    attack trigger's own "while saddled" gate is the new ``requires_
    saddled`` trigger-condition key, the same "checks the source's own
    live state" idiom `requires_equipped` uses.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec(
                    "search",
                    {
                        "criteria": {
                            "type": ["Creature", "Artifact", "Enchantment", "Planeswalker", "Battle"],
                            "without_type": "Land", "max_mana_value": 3,
                        },
                        "destination": "battlefield",
                    },
                )
            ],
            trigger={
                "event": EventType.ATTACKS, "condition": {"subject": "self"}, "requires_saddled": True,
            },
        ),
    ]


register("Guardian Sunmare", _guardian_sunmare)

from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ranger_captain_of_eos() -> list[AbilitySpec]:
    """Ranger-Captain of Eos (Creature — Human Soldier Ranger, {1}{W}{W})

    "When this creature enters, you may search your library for a creature
    card with mana value 1 or less, reveal it, put it into your hand, then
    shuffle.
    Sacrifice this creature: Your opponents can't cast noncreature spells
    this turn."

    The ETB is already parser-claimable as-is (`author_card.py reuse`
    confirms it); hand-authored only because the sacrifice ability's own
    "this turn" duration needs `GrantUntilEffect` to wrap the standing
    `cast_prohibition` static (Gaddock Teeg-shaped) instead of a
    permanent's own always-on line — `target_kind=None` since the
    prohibition is scoped by the static's own ``scope="opponents"``
    (read off the ability's ``source``, i.e. this card, which survives
    being sacrificed since `GameEffect.source` keeps its object reference
    regardless of zone), not by a chosen target.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec(
                    "search",
                    {"criteria": {"type": "creature", "max_mana_value": 1}, "destination": "hand"},
                )
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            optional=True,
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec(
                    "grant_until",
                    {
                        "static": {
                            "type": "cast_prohibition",
                            "params": {"scope": "opponents", "noncreature": True},
                        },
                        "duration": "end_of_turn",
                        "target_kind": None,
                    },
                )
            ],
            cost={"text": "Sacrifice ~"},
        ),
    ]


register("Ranger-Captain of Eos", _ranger_captain_of_eos)

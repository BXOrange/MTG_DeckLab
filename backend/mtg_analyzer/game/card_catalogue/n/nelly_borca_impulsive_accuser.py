from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nelly_borca_impulsive_accuser() -> list[AbilitySpec]:
    """Vigilance
    Whenever ~ attacks, suspect target creature. Then goad all suspected creatures.
    Whenever one or more creatures an opponent controls deal combat damage to one or more of
    your opponents, you and the controller of those creatures each draw a card.

    — MEC-104. The second ability is the aggregate combat-damage event with the
    ``opponents_batch`` marker (one trigger for the whole step, `binding.core.
    _contributor_condition`); the parser already emits exactly this head for the
    ``…an opponent controls…`` wording, so it is spelled out here only because the body
    ("you and the controller of those creatures") and the first ability's "then goad all
    suspected creatures" (`GoadEffect` ``selector="suspected_creatures"``) are Nelly-only.
    The other drawer is `DrawCardEffect` ``selector="event_player"``: the event's
    ``player_id`` is the contributing creatures' controller.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("suspect", {"target_kind": "creature"}),
                EffectSpec("goad", {"target_kind": None, "selector": "suspected_creatures"}),
            ],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("draw", {"count": 1}),
                EffectSpec("draw", {"count": 1, "selector": "event_player"}),
            ],
            trigger={
                "event": EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER,
                "condition": {
                    "subject": "group", "controller": "not_you", "other": False,
                    "filter": {"card_type": "creature"}, "recipient_is_opponent": True,
                },
                "contributors": {"min": 1},
                "opponents_batch": True,
            },
        ),
    ]


register("Nelly Borca, Impulsive Accuser", _nelly_borca_impulsive_accuser)

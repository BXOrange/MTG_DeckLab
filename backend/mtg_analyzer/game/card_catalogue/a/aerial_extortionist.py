from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _aerial_extortionist() -> list[AbilitySpec]:
    """Flying
    Whenever this creature enters or deals combat damage to a player, exile up to one target nonland permanent. For as
    long as that card remains exiled, its owner may cast it.
    Whenever another player casts a spell from anywhere other than their hand, draw a card.

    Flying is a keyword. "Enters or deals combat damage" is two abilities with the same body, as printed (RULE 603.2).
    The exile is Soul Partition's shape without the tax: `exile` with ``grant_owner_play_permission`` records a
    standing `exile_cast_condition` for the card's owner (RULE 400.7: it is a new object if it leaves exile). The last
    clause is a `SPELL_CAST` group trigger for non-controllers filtered by ``from_zone_not: hand`` (PAR-119).
    """
    exile_and_grant = EffectSpec("exile", {
        "target_kind": "nonland_permanent", "optional": True, "grant_owner_play_permission": True,
    })
    return [
        AbilitySpec("triggered", [exile_and_grant],
                    trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}}),
        AbilitySpec("triggered", [EffectSpec("exile", exile_and_grant.params)], trigger={
            "event": EventType.DAMAGE, "condition": {"subject": "self"},
            "filter": {"combat": True, "is_player": True},
        }),
        AbilitySpec("triggered", [EffectSpec("draw", {"count": 1})], trigger={
            "event": EventType.SPELL_CAST, "condition": {"subject": "group", "controller": "not_you"},
            "from_zone_not": "hand",
        }),
    ]


register("Aerial Extortionist", _aerial_extortionist)

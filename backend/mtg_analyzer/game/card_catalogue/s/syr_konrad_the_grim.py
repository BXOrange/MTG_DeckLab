from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _syr_konrad_the_grim() -> list[AbilitySpec]:
    """Whenever another creature dies, or a creature card is put into a graveyard from anywhere other than the battlefield, or a creature card leaves your graveyard, Syr Konrad deals 1 damage to each opponent.
    {1}{B}: Each player mills a card. (They each put the top card of their library into their graveyard.)

    — PLAY-ALL (Endless Punishment). The mill activation and the "another creature dies" head are the parser's. The other two heads are the `PUT_INTO_GRAVEYARD`
    group trigger with ``from_zone_not: battlefield`` and the `CARDS_LEFT_GRAVEYARD` trigger with ``graveyard_owner: you`` / ``left_graveyard_types: creature``
    (PAR-119). **Simplification**: cards that leave your graveyard in one batch (one instruction) trigger it once, not once per card.
    """
    ping = lambda: [EffectSpec("damage", {"amount": 1, "selector": "each_opponent"})]
    return [
        AbilitySpec(
            "triggered", ping(),
            trigger={"event": EventType.DIES, "condition": {"subject": "group", "controller": "any", "other": True, "type": "creature"}},
        ),
        AbilitySpec(
            "triggered", ping(),
            trigger={
                "event": EventType.PUT_INTO_GRAVEYARD,
                "condition": {"subject": "group", "controller": "any", "other": False, "type": "creature"},
                "from_zone_not": "battlefield",
            },
        ),
        AbilitySpec(
            "triggered", ping(),
            trigger={"event": EventType.CARDS_LEFT_GRAVEYARD, "graveyard_owner": "you", "left_graveyard_types": ["creature"]},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("for_each", {"over": {"players": "each_player"}, "effects": [
                {"type": "mill", "params": {"count": 1, "target_kind": "player"}},
            ]})],
            cost={"text": "{1}{b}"},
        ),
    ]


register("Syr Konrad, the Grim", _syr_konrad_the_grim)

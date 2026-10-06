from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _barbflare_gremlin() -> list[AbilitySpec]:
    """First strike, haste
    Whenever a player taps a land for mana, if this creature is tapped, that player adds one mana of any type that land produced. Then that land deals 1 damage to that player.

    — PLAY-ALL (Endless Punishment). First strike/haste are keywords. Mana Flare's triggered mana ability (`mirror_produced_mana` on a `TAPPED_FOR_MANA` group
    head over any player's land) gated by the RULE 603.4 ``source_state: tapped`` intervening-if, then Manabarbs' `damage` to the ``event_player`` with the
    land as the damage source (``dealer_event_key: instance_id`` — the event names the tapped land).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("mirror_produced_mana", {"count": 1, "player": {"of": "event_player", "as": "controller"}}),
                EffectSpec("damage", {"amount": 1, "selector": "event_player", "dealer_event_key": "instance_id"}),
            ],
            trigger={
                "event": EventType.TAPPED_FOR_MANA, "condition": {"subject": "group", "type": "land"},
                "mana_ability": True, "source_state": "tapped",
            },
        ),
    ]


register("Barbflare Gremlin", _barbflare_gremlin)
